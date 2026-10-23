/*
 * ff7-3d -- New 3DS viewer of one field background in stereoscopic 3D.
 * Copyright (C) 2026 Selim
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
 * General Public License as published by the Free Software Foundation, either version 3 of the License, or (at
 * your option) any later version. See LICENSE at the root of the repository.
 *
 * Reads a relief package (.f3d) generated on the player's PC by outils/atelier.py from their own disc, and draws
 * it on the top screen with the 3D slider. The stereo model, the depth substrate and the render-target setup
 * follow CTR-3D (https://github.com/zando95/CTR-3D, GPL-3.0); see source/relief.v.pica.
 *
 * Controls: the circle pad walks Cloud on the field's walkmesh (B held: he runs; the view follows him), the
 * D-pad shifts the view, L / R move the convergence plane, ZR hides him (the pad then scrolls the view),
 * Y opens the field list, SELECT toggles the frame stats, START quits. At start-up the bottom screen lists the
 * packages on the SD card. A package without a character (written with
 * --sans-personnage, or before version 4) falls back to the red test quad.
 */
#include <3ds.h>
#include <citro3d.h>
#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "modele_shbin.h"
#include "personnage.h"
#include "relief_shbin.h"

#define DOSSIER "sdmc:/3ds/ff7-3d"
#define ECRAN_L 400
#define ECRAN_H 240

#define DISPLAY_TRANSFER_FLAGS                                                                                         \
	(GX_TRANSFER_FLIP_VERT(0) | GX_TRANSFER_OUT_TILED(0) | GX_TRANSFER_RAW_COPY(0) |                                   \
	 GX_TRANSFER_IN_FORMAT(GX_TRANSFER_FMT_RGBA8) | GX_TRANSFER_OUT_FORMAT(GX_TRANSFER_FMT_RGB8) |                     \
	 GX_TRANSFER_SCALING(GX_TRANSFER_SCALE_NO))

/* Same header as outils/ff7_3d/relief.py, little-endian, 64 bytes. */
typedef struct
{
	char magie[4];
	u16 version;
	u16 pas;
	char nom[16];
	u16 tex_l, tex_h;
	s16 ox, oy;
	u16 zoom;
	u16 nb_sommets;
	u32 nb_indices;
	float z_convergence;
	float z_min, z_max;
} __attribute__((packed)) EnTeteF3d;

/* One exit of the field (package version 5): crossing the line loads <cible>.f3d (outils/ff7_3d/field.py, Porte). */
typedef struct
{
	s16 ligne[2][3];
	s16 arrivee[2];
	s16 triangle;
	char cible[9];
	u8 direction;
} __attribute__((packed)) PorteF3d;

#define PORTES_MAX 16

typedef struct
{
	EnTeteF3d e;
	C3D_Tex texture;
	float* sommets; /* linear memory: sx, sy, z, u, v */
	u16* indices;   /* linear memory */
	/* Occlusion of the original game (package version 2): one flat card per occluding tile, at z = 4 x ID,
	 * alpha-tested against a mask of the texels that occlude. Same vertex layout as the relief. */
	C3D_Tex masque;
	float* cartes;    /* 4 vertices per card */
	u16* idx_cartes;  /* 6 indices per card */
	u16 nb_cartes;
	float* temoin;    /* test character: a quad standing on the walkmesh */
	u16* idx_temoin;
	/* Field camera and walkmesh (package version 3). */
	float axes[3][3];
	float trans[3];
	u16 nb_triangles;
	s16 (*triangles)[3][3]; /* world x, y, z (z up) */
	/* The player's character (package version 4). */
	Personnage perso;
	int a_perso;
	/* Exits to other fields (package version 5). */
	PorteF3d portes[PORTES_MAX];
	u16 nb_portes;
} Relief;

/* One card of the package, as written by outils/ff7_3d/relief.py. */
typedef struct
{
	s16 x, y;
	u8 taille, couche;
	u16 id;
} __attribute__((packed)) CarteF3d;

static DVLB_s* s_dvlb;
static shaderProgram_s s_programme;
static DVLB_s* s_dvlb_modele;
static shaderProgram_s s_programme_modele;
static int s_uProjection, s_uH, s_uStereo;

/* Total disparity at infinity, in PS1 pixels, at full slider (CTR-3D uses 12). */
static const float ECART_STEREO = 6.0f; /* 12 (CTR-3D), then 8, were too strong on FF7's backgrounds at full slider */

#define PAQUETS_MAX 64

/* The .f3d packages on the SD card, sorted by name. */
static int lister_paquets(char noms[][32])
{
	DIR* d = opendir(DOSSIER);
	struct dirent* e;
	int n = 0, i, j;
	if (!d)
		return 0;
	while ((e = readdir(d)) != NULL && n < PAQUETS_MAX)
	{
		size_t l = strlen(e->d_name);
		if (l > 4 && l < 32 && strcmp(e->d_name + l - 4, ".f3d") == 0)
			snprintf(noms[n++], 32, "%s", e->d_name);
	}
	closedir(d);
	for (i = 1; i < n; i++)
		for (j = i; j > 0 && strcmp(noms[j - 1], noms[j]) > 0; j--)
		{
			char t[32];
			memcpy(t, noms[j], 32);
			memcpy(noms[j], noms[j - 1], 32);
			memcpy(noms[j - 1], t, 32);
		}
	return n;
}

/*
 * Field choice on the bottom screen: the pad or the D-pad moves, A loads, START quits. `courant` is the field
 * shown so far (selected first). Returns 1 with the chosen path, 0 to quit, -1 when there is no package.
 */
static int choisir_paquet(char* chemin, size_t taille, const char* courant)
{
	static char noms[PAQUETS_MAX][32];
	int n = lister_paquets(noms), choix = 0, i, attente = 0;
	if (!n)
		return -1;
	for (i = 0; i < n && courant; i++)
		if (strstr(courant, noms[i]))
			choix = i;
	consoleClear();
	while (aptMainLoop())
	{
		u32 appui, tenu;
		circlePosition pad;
		hidScanInput();
		appui = hidKeysDown();
		tenu = hidKeysHeld();
		hidCircleRead(&pad);
		if (appui & KEY_START)
			return 0;
		if (appui & KEY_A)
		{
			snprintf(chemin, taille, "%s/%s", DOSSIER, noms[choix]);
			consoleClear();
			return 1;
		}
		if (attente > 0)
			attente--;
		else if ((tenu & KEY_DDOWN) || pad.dy < -80)
			choix = (choix + 1) % n, attente = 10;
		else if ((tenu & KEY_DUP) || pad.dy > 80)
			choix = (choix + n - 1) % n, attente = 10;
		printf("\x1b[1;0Hff7-3d - choisir un ecran\n\n");
		for (i = 0; i < n && i < 20; i++)
			printf("%s %-28s\n", i == choix ? ">" : " ", noms[i]);
		printf("\n A charger   START quitter\n");
		gspWaitForVBlank();
	}
	return 0;
}

static void sommet(float* v, float sx, float sy, float z, const EnTeteF3d* e)
{
	v[0] = sx;
	v[1] = sy;
	v[2] = z;
	v[3] = (sx - e->ox) / (float)e->tex_l;
	v[4] = 1.0f - (sy - e->oy) / (float)e->tex_h;
}

static int charger_occlusion(FILE* f, Relief* r)
{
	u16 n, i;
	CarteF3d c;
	size_t octets_masque = (size_t)r->e.tex_l * r->e.tex_h;
	if (fread(&n, sizeof(n), 1, f) != 1)
		return 0;
	r->nb_cartes = n;
	r->cartes = linearAlloc((size_t)(n ? n : 1) * 4 * 5 * sizeof(float));
	r->idx_cartes = linearAlloc((size_t)(n ? n : 1) * 6 * sizeof(u16));
	if (!r->cartes || !r->idx_cartes)
		return 0;
	for (i = 0; i < n; i++)
	{
		float z, *v = r->cartes + (size_t)i * 20;
		u16* k = r->idx_cartes + (size_t)i * 6;
		if (fread(&c, sizeof(c), 1, f) != 1)
			return 0;
		z = 4.0f * c.id;
		sommet(v + 0, c.x, c.y, z, &r->e);
		sommet(v + 5, c.x + c.taille, c.y, z, &r->e);
		sommet(v + 10, c.x, c.y + c.taille, z, &r->e);
		sommet(v + 15, c.x + c.taille, c.y + c.taille, z, &r->e);
		k[0] = i * 4 + 0;
		k[1] = i * 4 + 2;
		k[2] = i * 4 + 1;
		k[3] = i * 4 + 1;
		k[4] = i * 4 + 2;
		k[5] = i * 4 + 3;
	}
	GSPGPU_FlushDataCache(r->cartes, (size_t)(n ? n : 1) * 4 * 5 * sizeof(float));
	GSPGPU_FlushDataCache(r->idx_cartes, (size_t)(n ? n : 1) * 6 * sizeof(u16));

	if (!C3D_TexInit(&r->masque, r->e.tex_l, r->e.tex_h, GPU_A8))
		return 0;
	if (fread(r->masque.data, 1, octets_masque, f) != octets_masque)
		return 0;
	C3D_TexFlush(&r->masque);
	C3D_TexSetFilter(&r->masque, GPU_NEAREST, GPU_NEAREST);
	C3D_TexSetWrap(&r->masque, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);

	{
		s16 m[9];
		s32 t[3];
		s16 zoom;
		int i2, j;
		if (fread(m, sizeof(m), 1, f) != 1 || fread(t, sizeof(t), 1, f) != 1 || fread(&zoom, 2, 1, f) != 1 ||
		    fread(&r->nb_triangles, 2, 1, f) != 1)
			return 0;
		for (i2 = 0; i2 < 3; i2++)
		{
			for (j = 0; j < 3; j++)
				r->axes[i2][j] = m[i2 * 3 + j] / 4096.0f;
			r->trans[i2] = (float)t[i2];
		}
		r->triangles = malloc((size_t)(r->nb_triangles ? r->nb_triangles : 1) * sizeof(*r->triangles));
		if (!r->triangles)
			return 0;
		if (r->nb_triangles && fread(r->triangles, sizeof(*r->triangles), r->nb_triangles, f) != r->nb_triangles)
			return 0;
		/* the neighbours by edge follow the triangles; the viewer refuses steps off the walkmesh without them */
		if (fseek(f, (long)r->nb_triangles * 3 * sizeof(s16), SEEK_CUR) != 0)
			return 0;
	}
	if (r->e.version >= 4)
	{
		int etat = personnage_charger(f, &r->perso);
		if (etat < 0)
			return 0;
		r->a_perso = etat;
	}
	if (r->e.version >= 5)
	{
		char magie[4];
		u16 n, i;
		if (fread(magie, 4, 1, f) != 1 || memcmp(magie, "PORT", 4) != 0 || fread(&n, 2, 1, f) != 1)
			return 0;
		for (i = 0; i < n; i++)
		{
			PorteF3d p;
			if (fread(&p, sizeof(p), 1, f) != 1)
				return 0;
			p.cible[8] = 0;
			if (r->nb_portes < PORTES_MAX)
				r->portes[r->nb_portes++] = p;
		}
	}

	r->temoin = linearAlloc(4 * 5 * sizeof(float));
	r->idx_temoin = linearAlloc(6 * sizeof(u16));
	if (!r->temoin || !r->idx_temoin)
		return 0;
	r->idx_temoin[0] = 0;
	r->idx_temoin[1] = 2;
	r->idx_temoin[2] = 1;
	r->idx_temoin[3] = 1;
	r->idx_temoin[4] = 2;
	r->idx_temoin[5] = 3;
	GSPGPU_FlushDataCache(r->idx_temoin, 6 * sizeof(u16));
	return 1;
}

static int charger_relief(const char* chemin, Relief* r)
{
	FILE* f = fopen(chemin, "rb");
	size_t octets_tex, octets_sommets, octets_indices;
	void* tampon;
	if (!f)
		return 0;
	if (fread(&r->e, sizeof(r->e), 1, f) != 1 || memcmp(r->e.magie, "F3D1", 4) != 0 || r->e.version < 3 || r->e.version > 5)
	{
		fclose(f);
		return 0;
	}
	fseek(f, 64, SEEK_SET);
	octets_tex = (size_t)r->e.tex_l * r->e.tex_h * 2;
	octets_sommets = (size_t)r->e.nb_sommets * 5 * sizeof(float);
	octets_indices = (size_t)r->e.nb_indices * sizeof(u16);

	if (!C3D_TexInit(&r->texture, r->e.tex_l, r->e.tex_h, GPU_RGB565))
	{
		fclose(f);
		return 0;
	}
	/* The workshop already wrote the texture in the PICA200's tiled order. */
	tampon = r->texture.data;
	if (fread(tampon, 1, octets_tex, f) != octets_tex)
		goto echec;
	C3D_TexFlush(&r->texture);
	C3D_TexSetFilter(&r->texture, GPU_LINEAR, GPU_LINEAR);
	C3D_TexSetWrap(&r->texture, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);

	r->sommets = linearAlloc(octets_sommets);
	r->indices = linearAlloc(octets_indices);
	if (!r->sommets || !r->indices)
		goto echec;
	if (fread(r->sommets, 1, octets_sommets, f) != octets_sommets ||
	    fread(r->indices, 1, octets_indices, f) != octets_indices)
		goto echec;
	GSPGPU_FlushDataCache(r->sommets, octets_sommets);
	GSPGPU_FlushDataCache(r->indices, octets_indices);
	if (!charger_occlusion(f, r))
		goto echec;
	fclose(f);
	return 1;

echec:
	fclose(f);
	return 0;
}

static void preparer_rendu(void)
{
	C3D_AttrInfo* attr;

	s_dvlb = DVLB_ParseFile((u32*)relief_shbin, relief_shbin_size);
	shaderProgramInit(&s_programme);
	shaderProgramSetVsh(&s_programme, &s_dvlb->DVLE[0]);
	C3D_BindProgram(&s_programme);
	s_uProjection = shaderInstanceGetUniformLocation(s_programme.vertexShader, "projection");
	s_uH = shaderInstanceGetUniformLocation(s_programme.vertexShader, "hParam");
	s_uStereo = shaderInstanceGetUniformLocation(s_programme.vertexShader, "stereo");

	/* The model program declares the same uniforms in the same order (projection, hParam, stereo), so they land
	 * in the same registers and one upload per eye serves both programs. */
	s_dvlb_modele = DVLB_ParseFile((u32*)modele_shbin, modele_shbin_size);
	shaderProgramInit(&s_programme_modele);
	shaderProgramSetVsh(&s_programme_modele, &s_dvlb_modele->DVLE[0]);

	attr = C3D_GetAttrInfo();
	AttrInfo_Init(attr);
	AttrInfo_AddLoader(attr, 0, GPU_FLOAT, 3); /* sx, sy, z */
	AttrInfo_AddLoader(attr, 1, GPU_FLOAT, 2); /* u, v */
	C3D_CullFace(GPU_CULL_NONE);
}

static void programme_relief(void)
{
	C3D_AttrInfo* attr;
	C3D_BindProgram(&s_programme);
	attr = C3D_GetAttrInfo();
	AttrInfo_Init(attr);
	AttrInfo_AddLoader(attr, 0, GPU_FLOAT, 3); /* sx, sy, z */
	AttrInfo_AddLoader(attr, 1, GPU_FLOAT, 2); /* u, v */
}

/* The character: positions projected on the CPU, PS1 polygon colours, depth-tested against the occlusion cards. */
static void dessiner_personnage(Personnage* p)
{
	C3D_AttrInfo* attr;
	C3D_BufInfo* buf;
	C3D_TexEnv* env;
	C3D_BindProgram(&s_programme_modele);
	attr = C3D_GetAttrInfo();
	AttrInfo_Init(attr);
	AttrInfo_AddLoader(attr, 0, GPU_FLOAT, 3); /* sx, sy, z */
	AttrInfo_AddLoader(attr, 1, GPU_FLOAT, 4); /* r, g, b, a */
	buf = C3D_GetBufInfo();
	BufInfo_Init(buf);
	BufInfo_Add(buf, p->tampon, 7 * sizeof(float), 2, 0x10);
	env = C3D_GetTexEnv(0);
	C3D_TexEnvInit(env);
	C3D_TexEnvSrc(env, C3D_Both, GPU_PRIMARY_COLOR, 0, 0);
	C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
	C3D_AlphaTest(false, GPU_ALWAYS, 0);
	C3D_DepthTest(true, GPU_LEQUAL, GPU_WRITE_ALL);
	C3D_DrawArrays(GPU_TRIANGLES, 0, p->nb_triangles * 3);
}

static void lier_sommets(const void* sommets)
{
	C3D_BufInfo* buf = C3D_GetBufInfo();
	BufInfo_Init(buf);
	BufInfo_Add(buf, sommets, 5 * sizeof(float), 2, 0x10);
}

static void combiner(C3D_Tex* texture, u32 couleur)
{
	C3D_TexEnv* env = C3D_GetTexEnv(0);
	C3D_TexEnvInit(env);
	if (texture)
	{
		C3D_TexBind(0, texture);
		C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, 0, 0);
	}
	else
	{
		C3D_TexEnvSrc(env, C3D_Both, GPU_CONSTANT, 0, 0);
		C3D_TexEnvColor(env, couleur);
	}
	C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
}

/* GTE projection of the field camera: c = R v + t, sx = H cx / cz, sy = H cy / cz (outils/ff7_3d/camera.py). */
static float projeter(const Relief* r, const float v[3], float* sx, float* sy)
{
	float c[3];
	int i;
	for (i = 0; i < 3; i++)
		c[i] = r->axes[i][0] * v[0] + r->axes[i][1] * v[1] + r->axes[i][2] * v[2] + r->trans[i];
	if (c[2] < 1.0f)
		c[2] = 1.0f;
	*sx = r->e.zoom * c[0] / c[2];
	*sy = r->e.zoom * c[1] / c[2];
	return c[2];
}

/* Height of walkmesh triangle i under (x, y), or 0 when (x, y) is outside it. */
static int sol_du_triangle(const Relief* r, int i, float x, float y, float* z)
{
	const s16(*t)[3] = r->triangles[i];
	float ax = t[0][0], ay = t[0][1], bx = t[1][0], by = t[1][1], cx = t[2][0], cy = t[2][1];
	float aire = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
	float w0, w1, w2;
	if (aire > -1e-3f && aire < 1e-3f)
		return 0;
	w0 = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / aire;
	w1 = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / aire;
	w2 = 1.0f - w0 - w1;
	if (w0 >= -1e-4f && w1 >= -1e-4f && w2 >= -1e-4f)
	{
		*z = w0 * t[0][2] + w1 * t[1][2] + w2 * t[2][2];
		return 1;
	}
	return 0;
}

/* Height of the floor under (x, y), or 0 when (x, y) is off the walkmesh. */
static int sol(const Relief* r, float x, float y, float* z)
{
	int i;
	for (i = 0; i < r->nb_triangles; i++)
		if (sol_du_triangle(r, i, x, y, z))
			return 1;
	return 0;
}

/* Height of the test character, in world units. A guess for now: Cloud's real model comes with step 10. */
#define HAUTEUR_TEMOIN 100.0f

/* Stands the test character at its world position: a quad from the feet to the head, both projected, so its
 * size and depth come from the field camera exactly like a real model's. Returns the feet's screen position. */
static void placer_temoin(Relief* r, const float pied[3], float* px, float* py)
{
	float tete[3] = {pied[0], pied[1], pied[2] + HAUTEUR_TEMOIN};
	float sxp, syp, sxt, syt, zp, zt, demi;
	zp = projeter(r, pied, &sxp, &syp);
	zt = projeter(r, tete, &sxt, &syt);
	demi = 0.2f * (syp - syt);
	sommet(r->temoin + 0, sxt - demi, syt, zt, &r->e);
	sommet(r->temoin + 5, sxt + demi, syt, zt, &r->e);
	sommet(r->temoin + 10, sxp - demi, syp, zp, &r->e);
	sommet(r->temoin + 15, sxp + demi, syp, zp, &r->e);
	GSPGPU_FlushDataCache(r->temoin, 4 * 5 * sizeof(float));
	*px = sxp;
	*py = syp;
}

/*
 * One eye. The order is the design of docs/ff7-3d/README.md (layer D):
 * 1. the relief: colour only, no depth writes (the stereo depth is for the eyes, not for sorting);
 * 2. the occlusion cards of the original game: depth only, alpha-tested against the mask (a blended texel,
 *    STP bit of a semi-transparent tile, is not in the mask: it never occludes);
 * 3. the game's objects (here the test object): depth test against the cards, one flat depth per polygon like
 *    the PS1 ordering table (personnage.h), the tile winning at an equal slot.
 * Mtx_OrthoTilt maps a larger vertex z to a smaller stored depth: LEQUAL with the clear at the far end
 * (CTR-3D, n3ds_backend.c).
 */
/* One line with the fields the exits lead to, each once: where the player can walk from here. */
static void afficher_sorties(const Relief* r)
{
	char ligne[41] = "sorties :";
	size_t n = strlen(ligne);
	int i, j;
	for (i = 0; i < r->nb_portes; i++)
	{
		char nom[10];
		int deja = 0;
		memcpy(nom, r->portes[i].cible, 9);
		nom[9] = 0;
		for (j = 0; j < i && !deja; j++)
			deja = strncmp(r->portes[j].cible, r->portes[i].cible, 9) == 0;
		if (deja || !nom[0] || n + 1 + strlen(nom) >= sizeof(ligne))
			continue;
		n += (size_t)snprintf(ligne + n, sizeof(ligne) - n, " %s", nom);
	}
	if (!r->nb_portes)
		snprintf(ligne + n, sizeof(ligne) - n, " aucune");
	printf("%-40s\n", ligne);
}

static void dessiner(Relief* r, float cx, float cy, const float stereo[4], int avec_temoin)
{
	C3D_Mtx projection;
	/* The visible window, in PS1 screen pixels; y grows downwards like on the PS1 (same construction as CTR-3D).
	 * The upside-down picture of the first console run came from the texture rows, not from this matrix. */
	Mtx_OrthoTilt(&projection, cx - ECRAN_L / 2, cx + ECRAN_L / 2, cy + ECRAN_H / 2, cy - ECRAN_H / 2, -32769.0f,
	              32769.0f, true);
	C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &projection);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uH, (float)r->e.zoom, 1.0f / (float)r->e.zoom, 0.0f, 0.0f);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uStereo, stereo[0], stereo[1], stereo[2], stereo[3]);

	programme_relief();
	lier_sommets(r->sommets);
	combiner(&r->texture, 0);
	C3D_AlphaTest(false, GPU_ALWAYS, 0);
	C3D_DepthTest(true, GPU_ALWAYS, GPU_WRITE_COLOR);
	C3D_DrawElements(GPU_TRIANGLES, (int)r->e.nb_indices, C3D_UNSIGNED_SHORT, r->indices);

	if (r->nb_cartes)
	{
		lier_sommets(r->cartes);
		combiner(&r->masque, 0);
		C3D_AlphaTest(true, GPU_GREATER, 127);
		C3D_DepthTest(true, GPU_LEQUAL, GPU_WRITE_DEPTH);
		C3D_DrawElements(GPU_TRIANGLES, r->nb_cartes * 6, C3D_UNSIGNED_SHORT, r->idx_cartes);
	}

	if (avec_temoin && r->a_perso)
		dessiner_personnage(&r->perso);
	else if (avec_temoin)
	{
		lier_sommets(r->temoin);
		combiner(NULL, 0xFF4875E0); /* ABGR: a warm red, easy to see over Midgar's greens */
		C3D_AlphaTest(false, GPU_ALWAYS, 0);
		C3D_DepthTest(true, GPU_LEQUAL, GPU_WRITE_ALL);
		C3D_DrawElements(GPU_TRIANGLES, 6, C3D_UNSIGNED_SHORT, r->idx_temoin);
	}
}

/* u = 1 - C/depth, softened on the near side (u' = u / (1 + max(-u, 0))), p = k u': far content recedes up to k,
 * near content pops out up to k, smoothly (CTR-3D clamps at 2k: too strong at full slider on these backgrounds,
 * and the hard edge of the clamp showed). */
static void vecteur_oeil(float k, float convergence, float v[4])
{
	float a = k < 0 ? -k : k;
	v[0] = k;
	v[1] = convergence;
	v[2] = -a;
	v[3] = a;
}

static void relief_liberer(Relief* r)
{
	if (r->texture.data)
		C3D_TexDelete(&r->texture);
	if (r->masque.data)
		C3D_TexDelete(&r->masque);
	if (r->cartes)
		linearFree(r->cartes);
	if (r->idx_cartes)
		linearFree(r->idx_cartes);
	if (r->temoin)
		linearFree(r->temoin);
	if (r->idx_temoin)
		linearFree(r->idx_temoin);
	free(r->triangles);
	personnage_liberer(&r->perso);
	if (r->sommets)
		linearFree(r->sommets);
	if (r->indices)
		linearFree(r->indices);
	memset(r, 0, sizeof(*r));
}

/* Everything the viewer keeps about the field it shows and the character in it. */
typedef struct
{
	Relief relief;
	CameraTerrain cam;
	float pied[3];
	float angle, image; /* Cloud: facing (radians, 0 = towards -y) and animation frame */
	int anim;           /* 0 standing, 1 walking, 2 running */
	int temoin;         /* the character is shown (ZR) */
	float convergence;  /* depth that sits on the screen plane, this frame */
	float facteur;      /* L / R: the convergence relative to Cloud's depth (1 = Cloud on the screen plane) */
	float xmin, xmax, ymin, ymax; /* where the view centre may go, so the window stays on the background */
} Etat;

#define REGLAGES DOSSIER "/reglages.txt"

/* The stereo setting the player chose with L / R, kept across fields and sessions. */
static float lire_facteur(void)
{
	float f = 1.0f;
	FILE* fic = fopen(REGLAGES, "r");
	if (fic)
	{
		if (fscanf(fic, "convergence %f", &f) != 1 || f < 0.25f || f > 4.0f)
			f = 1.0f;
		fclose(fic);
	}
	return f;
}

static void ecrire_facteur(float f)
{
	FILE* fic = fopen(REGLAGES, "w");
	if (fic)
	{
		fprintf(fic, "convergence %.3f\n", f);
		fclose(fic);
	}
}

static void attendre_start(const char* message)
{
	printf("%s\n\nSTART pour quitter.\n", message);
	while (aptMainLoop())
	{
		hidScanInput();
		if (hidKeysDown() & KEY_START)
			break;
		gspWaitForVBlank();
	}
}

/* Loads a package and stands the character at the centre of the walkmesh, facing the camera. */
static int entrer(Etat* et, const char* chemin)
{
	Relief* r = &et->relief;
	relief_liberer(r);
	if (!charger_relief(chemin, r))
		return 0;
	et->convergence = -1.0f; /* set on the first frame, without easing */
	memcpy(et->cam.axes, r->axes, sizeof(et->cam.axes));
	memcpy(et->cam.trans, r->trans, sizeof(et->cam.trans));
	et->cam.zoom = r->e.zoom;
	/* first look: facing the camera, so his face shows */
	et->angle = atan2f(-r->axes[2][0], r->axes[2][1]);
	et->anim = 0;
	et->image = 0.0f;
	et->temoin = r->nb_triangles != 0;
	if (r->nb_triangles)
	{
		/* start at the centre of the walkmesh triangle that falls nearest the middle of the background: the
		 * walkmesh often reaches past the picture (MD1_1: up to 290 pixels on the right), so its own centre may
		 * be off screen (same rule as the workshop's preview, outils/ff7_3d/rendu.py, depart) */
		int t, k, meilleur = 0;
		float mx = r->e.ox + r->e.tex_l * 0.5f, my = r->e.oy + r->e.tex_h * 0.5f, d_min = 1e30f;
		for (t = 0; t < r->nb_triangles; t++)
		{
			float c[3], sx, sy, d;
			for (k = 0; k < 3; k++)
				c[k] = (r->triangles[t][0][k] + r->triangles[t][1][k] + r->triangles[t][2][k]) / 3.0f;
			projeter(r, c, &sx, &sy);
			d = (sx - mx) * (sx - mx) + (sy - my) * (sy - my);
			if (d < d_min)
				d_min = d, meilleur = t;
		}
		for (k = 0; k < 3; k++)
			et->pied[k] = (r->triangles[meilleur][0][k] + r->triangles[meilleur][1][k] + r->triangles[meilleur][2][k]) / 3.0f;
	}
	et->xmin = r->e.ox + ECRAN_L / 2;
	et->xmax = r->e.ox + r->e.tex_l - ECRAN_L / 2;
	et->ymin = r->e.oy + ECRAN_H / 2;
	et->ymax = r->e.oy + r->e.tex_h - ECRAN_H / 2;
	if (et->xmin > et->xmax)
		et->xmin = et->xmax = r->e.ox + r->e.tex_l / 2;
	if (et->ymin > et->ymax)
		et->ymin = et->ymax = r->e.oy + r->e.tex_h / 2;
	consoleClear();
	return 1;
}

/* Walk on the walkmesh: the pad moves the character along the screen's right and forward axes, projected on the
 * ground; a step that leaves the walkmesh is refused, like a blocked edge. */
static void marcher(Etat* et, const circlePosition* pad, u32 tenu)
{
	Relief* r = &et->relief;
	float dx = pad->dx / 156.0f, dy = pad->dy / 156.0f, nx, ny, nz, avant[2], droite[2], n;
	/* walk about 3 world units per frame (Cloud is 126 high), run twice that with B */
	float vitesse = (tenu & KEY_B) ? 6.0f : 3.0f;
	float mx, my, force;
	droite[0] = r->axes[0][0];
	droite[1] = r->axes[0][1];
	avant[0] = r->axes[2][0];
	avant[1] = r->axes[2][1];
	n = sqrtf(droite[0] * droite[0] + droite[1] * droite[1]);
	if (n > 0)
		droite[0] /= n, droite[1] /= n;
	n = sqrtf(avant[0] * avant[0] + avant[1] * avant[1]);
	if (n > 0)
		avant[0] /= n, avant[1] /= n;
	mx = dx * droite[0] + dy * avant[0];
	my = dx * droite[1] + dy * avant[1];
	force = sqrtf(dx * dx + dy * dy);
	if (force > 1.0f)
		force = 1.0f;
	if (force <= 0.15f)
	{
		et->anim = 0;
		et->image = 0.0f;
		return;
	}
	n = sqrtf(mx * mx + my * my) + 1e-6f;
	nx = et->pied[0] + vitesse * mx / n * force;
	ny = et->pied[1] + vitesse * my / n * force;
	/* turn towards the step; at angle 0 he looks towards -y */
	et->angle = atan2f(mx, -my);
	et->anim = (tenu & KEY_B) ? 2 : 1;
	/* the PS1 field plays one animation frame per 30 Hz frame: half a frame per 60 Hz frame */
	et->image += 0.5f * (force < 0.5f ? 0.5f : force);
	if (sol(r, nx, ny, &nz))
	{
		et->pied[0] = nx;
		et->pied[1] = ny;
		et->pied[2] = nz;
	}
}

/* Does the step a -> b cross the segment p -> q (on the ground plane)? */
static int croise(float ax, float ay, float bx, float by, float px, float py, float qx, float qy)
{
	float d1 = (qx - px) * (ay - py) - (qy - py) * (ax - px);
	float d2 = (qx - px) * (by - py) - (qy - py) * (bx - px);
	float d3 = (bx - ax) * (py - ay) - (by - ay) * (px - ax);
	float d4 = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax);
	return ((d1 > 0) != (d2 > 0)) && ((d3 > 0) != (d4 > 0));
}

/*
 * Field exits: when the last step crossed an exit line, load the target field if its package is on the SD card and
 * stand Cloud where the game puts him (the exit's arrival point and direction). Returns 1 when the field changed.
 * Without the package, the step is undone and the bottom screen says which field to generate.
 */
static int franchir(Etat* et, const float avant[3], char* chemin, size_t taille)
{
	Relief* r = &et->relief;
	u16 i;
	for (i = 0; i < r->nb_portes; i++)
	{
		const PorteF3d* p = &r->portes[i];
		char cible[256], nom[16];
		PorteF3d porte;
		FILE* f;
		int k;
		float z;
		if (!croise(avant[0], avant[1], et->pied[0], et->pied[1], p->ligne[0][0], p->ligne[0][1], p->ligne[1][0],
		            p->ligne[1][1]))
			continue;
		for (k = 0; k < 15 && p->cible[k]; k++)
			nom[k] = (p->cible[k] >= 'A' && p->cible[k] <= 'Z') ? p->cible[k] - 'A' + 'a' : p->cible[k];
		nom[k] = 0;
		snprintf(cible, sizeof(cible), "%s/%s.f3d", DOSSIER, nom);
		f = fopen(cible, "rb");
		if (!f)
		{
			memcpy(et->pied, avant, sizeof(et->pied));
			printf("\x1b[27;0H%-8s absent : generez-le    \navec outils/atelier.py %-8s  ", p->cible, p->cible);
			return 0;
		}
		fclose(f);
		porte = *p; /* r is reloaded below */
		if (!entrer(et, cible))
			return -1;
		snprintf(chemin, taille, "%s", cible);
		et->pied[0] = porte.arrivee[0];
		et->pied[1] = porte.arrivee[1];
		/* the game names the walkmesh triangle under the arrival (pcPosI): its height first, so a floor that
		 * passes under a bridge cannot catch Cloud; the first triangle under (x, y) otherwise */
		if (porte.triangle >= 0 && porte.triangle < et->relief.nb_triangles &&
		    sol_du_triangle(&et->relief, porte.triangle, et->pied[0], et->pied[1], &z))
			et->pied[2] = z;
		else if (sol(&et->relief, et->pied[0], et->pied[1], &z))
			et->pied[2] = z;
		else if (porte.triangle >= 0 && porte.triangle < et->relief.nb_triangles)
		{
			const s16(*t)[3] = et->relief.triangles[porte.triangle];
			et->pied[2] = (t[0][2] + t[1][2] + t[2][2]) / 3.0f;
		}
		/* the entity's direction byte: 256 steps per turn, the same rotation as the workshop's (rendu.py) */
		et->angle = porte.direction * (2.0f * 3.14159265f / 256.0f);
		return 1;
	}
	return 0;
}

int main(int argc, char** argv)
{
	static Etat et;
	char chemin[256];
	C3D_RenderTarget *gauche, *droite;
	float cx = 0.0f, cy = 0.0f;
	float decal_x = 0.0f, decal_y = 0.0f;
	int stats = 1;
	float ms_pose = 0.0f; /* CPU time of personnage_poser (projection of Cloud's vertices), smoothed */
	u64 dernier = 0;
	float ms = 0.0f;

	gfxInitDefault();
	gfxSet3D(true);
	consoleInit(GFX_BOTTOM, NULL);
	C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);

	printf("ff7-3d - visualiseur de relief\n\n");
	if (argc > 1)
		snprintf(chemin, sizeof(chemin), "%s", argv[1]);
	else
	{
		int choix = choisir_paquet(chemin, sizeof(chemin), NULL);
		if (choix < 0)
			attendre_start("Aucun paquet .f3d dans\n" DOSSIER "\n\nGenerez-le sur PC avec\noutils/atelier.py (voir port3ds/README.md).");
		if (choix <= 0)
		{
			C3D_Fini();
			gfxExit();
			return 0;
		}
	}
	et.facteur = lire_facteur();
	if (!entrer(&et, chemin))
	{
		printf("Paquet illisible :\n%s\n", chemin);
		attendre_start("");
		C3D_Fini();
		gfxExit();
		return 0;
	}

	gauche = C3D_RenderTargetCreate(ECRAN_H, ECRAN_L, GPU_RB_RGBA8, GPU_RB_DEPTH24_STENCIL8);
	C3D_RenderTargetSetOutput(gauche, GFX_TOP, GFX_LEFT, DISPLAY_TRANSFER_FLAGS);
	droite = C3D_RenderTargetCreate(ECRAN_H, ECRAN_L, GPU_RB_RGBA8, GPU_RB_DEPTH24_STENCIL8);
	C3D_RenderTargetSetOutput(droite, GFX_TOP, GFX_RIGHT, DISPLAY_TRANSFER_FLAGS);
	preparer_rendu();

	while (aptMainLoop())
	{
		Relief* r = &et.relief;
		u32 appui, tenu;
		circlePosition pad;
		float curseur, k, oeil[2][4];
		int actif;
		u64 maintenant;

		hidScanInput();
		appui = hidKeysDown();
		tenu = hidKeysHeld();
		if (appui & KEY_START)
			break;
		if (appui & KEY_SELECT)
			stats = !stats;
		if (appui & KEY_Y)
		{
			/* back to the field list; the chosen field is loaded, or the current one stays */
			char nouveau[256];
			int choix = choisir_paquet(nouveau, sizeof(nouveau), chemin);
			if (choix == 0)
				break;
			if (choix > 0 && strcmp(nouveau, chemin) != 0)
			{
				if (entrer(&et, nouveau))
					snprintf(chemin, sizeof(chemin), "%s", nouveau);
				else if (!entrer(&et, chemin))
					break;
				decal_x = decal_y = 0.0f;
			}
			consoleClear();
			continue;
		}
		hidCircleRead(&pad);
		if (et.temoin)
		{
			float avant[3];
			int change;
			memcpy(avant, et.pied, sizeof(avant));
			marcher(&et, &pad, tenu);
			change = franchir(&et, avant, chemin, sizeof(chemin));
			if (change < 0)
				break;
			if (change > 0)
			{
				decal_x = decal_y = 0.0f;
				continue;
			}
		}
		else
		{
			decal_x += pad.dx / 40.0f;
			decal_y -= pad.dy / 40.0f;
		}
		decal_x += ((tenu & KEY_DRIGHT) ? 2 : 0) - ((tenu & KEY_DLEFT) ? 2 : 0);
		decal_y += ((tenu & KEY_DDOWN) ? 2 : 0) - ((tenu & KEY_DUP) ? 2 : 0);
		if (appui & KEY_ZR)
			et.temoin = !et.temoin && r->nb_triangles;
		/* the convergence follows Cloud: he stays on the screen plane, the background recedes behind him and what
		 * is nearer than him comes out; L / R move that plane relative to him, and the choice is saved */
		if (tenu & KEY_R)
			et.facteur = et.facteur * 1.02f > 4.0f ? 4.0f : et.facteur * 1.02f;
		if (tenu & KEY_L)
			et.facteur = et.facteur / 1.02f < 0.25f ? 0.25f : et.facteur / 1.02f;
		if (hidKeysUp() & (KEY_L | KEY_R))
			ecrire_facteur(et.facteur);
		if (et.temoin && r->a_perso)
		{
			float px, py, ph, pz;
			u64 t0 = svcGetSystemTick();
			personnage_poser(&r->perso, &et.cam, et.pied, et.angle, et.anim, et.image, &px, &py, &ph, &pz);
			ms_pose = ms_pose * 0.9f + (float)(svcGetSystemTick() - t0) / CPU_TICKS_PER_MSEC * 0.1f;
			et.convergence = et.convergence < 0 ? pz * et.facteur : et.convergence + (pz * et.facteur - et.convergence) * 0.1f;
			/* the view follows him, centred on his waist, like the field camera scroll */
			cx = px + decal_x;
			cy = 0.5f * (py + ph) + decal_y;
		}
		else if (et.temoin)
		{
			float px, py;
			placer_temoin(r, et.pied, &px, &py);
			et.convergence = et.convergence < 0 ? r->e.z_convergence * et.facteur
			                                    : et.convergence + (r->e.z_convergence * et.facteur - et.convergence) * 0.1f;
			/* the view follows the character, like the field camera scroll */
			cx = px + decal_x;
			cy = py - 40.0f + decal_y;
		}
		else
		{
			cx = decal_x;
			cy = decal_y;
			et.convergence = et.convergence < 0 ? r->e.z_convergence * et.facteur
			                                    : et.convergence + (r->e.z_convergence * et.facteur - et.convergence) * 0.1f;
		}
		cx = cx < et.xmin ? et.xmin : (cx > et.xmax ? et.xmax : cx);
		cy = cy < et.ymin ? et.ymin : (cy > et.ymax ? et.ymax : cy);

		curseur = osGet3DSliderState();
		actif = curseur > 0.01f;
		k = actif ? curseur * ECART_STEREO * 0.5f : 0.0f;
		vecteur_oeil(-k, et.convergence, oeil[0]); /* left eye */
		vecteur_oeil(k, et.convergence, oeil[1]);  /* right eye: far content shifts right */

		C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
		C3D_RenderTargetClear(gauche, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
		C3D_FrameDrawOn(gauche);
		dessiner(r, cx, cy, oeil[0], et.temoin);
		if (actif)
		{
			C3D_RenderTargetClear(droite, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
			C3D_FrameDrawOn(droite);
			dessiner(r, cx, cy, oeil[1], et.temoin);
		}
		C3D_FrameEnd(0);

		maintenant = osGetTime();
		if (dernier)
			ms = ms * 0.9f + (float)(maintenant - dernier) * 0.1f;
		dernier = maintenant;
		if (stats)
		{
			printf("\x1b[4;0H%s  %u sommets, %lu triangles      \n", r->e.nom, r->e.nb_sommets,
			       (unsigned long)(r->e.nb_indices / 3));
			printf("image : %5.1f ms (%4.1f i/s)        \n", ms, ms > 0 ? 1000.0f / ms : 0.0f);
			printf("curseur 3D : %3.0f %%  ecart : %4.1f px    \n", curseur * 100.0f, 2 * k);
			printf("convergence z : %6.0f x%.2f (L / R) \n", et.convergence, et.facteur);
			printf("vue : %5.0f, %5.0f (pad)          \n", cx, cy);
			if (r->a_perso)
				printf("Cloud : %6.0f %6.0f %5.0f a%d i%2d  \n", et.pied[0], et.pied[1], et.pied[2], et.anim,
				       (int)et.image % (r->perso.nb_images[et.anim] ? r->perso.nb_images[et.anim] : 1));
			if (r->a_perso)
				printf("pose de Cloud : %4.2f ms CPU        \n", ms_pose);
			else
				printf("temoin : %6.0f %6.0f %5.0f (ZR)  \n", et.pied[0], et.pied[1], et.pied[2]);
			printf("cartes d'occlusion : %u            \n", r->nb_cartes);
			afficher_sorties(r);
			printf("GPU %4.1f %%  CPU %4.1f %%            \n", C3D_GetDrawingTime() * 6.0f,
			       C3D_GetProcessingTime() * 6.0f);
			printf("\nSELECT stats  ZR %s  B courir\nY ecrans  START quitter\n", r->a_perso ? "Cloud" : "temoin");
		}
	}

	relief_liberer(&et.relief);
	shaderProgramFree(&s_programme);
	DVLB_Free(s_dvlb);
	shaderProgramFree(&s_programme_modele);
	DVLB_Free(s_dvlb_modele);
	C3D_RenderTargetDelete(gauche);
	C3D_RenderTargetDelete(droite);
	C3D_Fini();
	gfxExit();
	return 0;
}
