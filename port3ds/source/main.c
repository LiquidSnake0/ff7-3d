/*
 * ff7-3d -- New 3DS viewer of one field background in stereoscopic 3D.
 * Copyright (C) 2026 Selim Selimi
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
 * General Public License as published by the Free Software Foundation, either version 3 of the License, or (at
 * your option) any later version. See LICENSE at the root of the repository.
 *
 * Reads a relief package (.f3d) generated on the player's PC by outils/atelier.py from their own disc, and draws
 * it on the top screen with the 3D slider. The stereo model, the depth substrate and the render-target setup
 * follow CTR-3D (https://github.com/zando95/CTR-3D, GPL-3.0); see source/relief.v.pica.
 *
 * Controls: the circle pad walks a test character on the field's walkmesh (the view follows it), the D-pad
 * shifts the view, L / R move the convergence plane, ZR hides the character (the pad then scrolls the view),
 * SELECT toggles the frame stats, START quits.
 */
#include <3ds.h>
#include <citro3d.h>
#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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
static int s_uProjection, s_uH, s_uStereo;

/* CTR-3D's stereo tuning: total disparity at infinity, in PS1 pixels, at full slider. */
static const float ECART_STEREO = 12.0f;

static int chercher_paquet(char* chemin, size_t taille)
{
	DIR* d = opendir(DOSSIER);
	struct dirent* e;
	if (!d)
		return 0;
	while ((e = readdir(d)) != NULL)
	{
		size_t n = strlen(e->d_name);
		if (n > 4 && strcmp(e->d_name + n - 4, ".f3d") == 0)
		{
			snprintf(chemin, taille, "%s/%.200s", DOSSIER, e->d_name);
			closedir(d);
			return 1;
		}
	}
	closedir(d);
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
	if (fread(&r->e, sizeof(r->e), 1, f) != 1 || memcmp(r->e.magie, "F3D1", 4) != 0 || r->e.version != 3)
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

	attr = C3D_GetAttrInfo();
	AttrInfo_Init(attr);
	AttrInfo_AddLoader(attr, 0, GPU_FLOAT, 3); /* sx, sy, z */
	AttrInfo_AddLoader(attr, 1, GPU_FLOAT, 2); /* u, v */
	C3D_CullFace(GPU_CULL_NONE);
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

/* Height of the floor under (x, y), or 0 when (x, y) is off the walkmesh. */
static int sol(const Relief* r, float x, float y, float* z)
{
	int i;
	for (i = 0; i < r->nb_triangles; i++)
	{
		const s16(*t)[3] = r->triangles[i];
		float ax = t[0][0], ay = t[0][1], bx = t[1][0], by = t[1][1], cx = t[2][0], cy = t[2][1];
		float aire = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
		float w0, w1, w2;
		if (aire > -1e-3f && aire < 1e-3f)
			continue;
		w0 = ((bx - x) * (cy - y) - (by - y) * (cx - x)) / aire;
		w1 = ((cx - x) * (ay - y) - (cy - y) * (ax - x)) / aire;
		w2 = 1.0f - w0 - w1;
		if (w0 >= -1e-4f && w1 >= -1e-4f && w2 >= -1e-4f)
		{
			*z = w0 * t[0][2] + w1 * t[1][2] + w2 * t[2][2];
			return 1;
		}
	}
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
 * 2. the occlusion cards of the original game: depth only, alpha-tested against the mask;
 * 3. the game's objects (here the test object): depth test against the cards.
 * Mtx_OrthoTilt maps a larger vertex z to a smaller stored depth: LEQUAL with the clear at the far end
 * (CTR-3D, n3ds_backend.c).
 */
static void dessiner(Relief* r, float cx, float cy, const float stereo[4], int avec_temoin)
{
	C3D_Mtx projection;
	/* The visible window, in PS1 screen pixels; y grows downwards like on the PS1. */
	Mtx_OrthoTilt(&projection, cx - ECRAN_L / 2, cx + ECRAN_L / 2, cy + ECRAN_H / 2, cy - ECRAN_H / 2, -32769.0f,
	              32769.0f, true);
	C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &projection);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uH, (float)r->e.zoom, 1.0f / (float)r->e.zoom, 0.0f, 0.0f);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uStereo, stereo[0], stereo[1], stereo[2], stereo[3]);

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

	if (avec_temoin)
	{
		lier_sommets(r->temoin);
		combiner(NULL, 0xFF4875E0); /* ABGR: a warm red, easy to see over Midgar's greens */
		C3D_AlphaTest(false, GPU_ALWAYS, 0);
		C3D_DepthTest(true, GPU_LEQUAL, GPU_WRITE_ALL);
		C3D_DrawElements(GPU_TRIANGLES, 6, C3D_UNSIGNED_SHORT, r->idx_temoin);
	}
}

/* p = k - kC/depth, clamped: far content recedes up to k, near content pops out up to 2k (CTR-3D's default). */
static void vecteur_oeil(float k, float convergence, float v[4])
{
	float a = k < 0 ? -k : k;
	v[0] = k;
	v[1] = k * convergence;
	v[2] = -2.0f * a;
	v[3] = 2.0f * a;
}

int main(int argc, char** argv)
{
	Relief relief;
	char chemin[256];
	C3D_RenderTarget *gauche, *droite;
	float cx = 0.0f, cy = 0.0f, convergence;
	float pied[3] = {0, 0, 0};
	float decal_x = 0.0f, decal_y = 0.0f;
	int temoin = 1;
	float xmin, xmax, ymin, ymax;
	int stats = 1;
	u64 dernier = 0;
	float ms = 0.0f;

	gfxInitDefault();
	gfxSet3D(true);
	consoleInit(GFX_BOTTOM, NULL);
	C3D_Init(C3D_DEFAULT_CMDBUF_SIZE);

	printf("ff7-3d - visualiseur de relief\n\n");
	if (argc > 1)
		snprintf(chemin, sizeof(chemin), "%s", argv[1]);
	else if (!chercher_paquet(chemin, sizeof(chemin)))
	{
		printf("Aucun paquet .f3d dans\n%s\n\nGenerez-le sur PC avec\noutils/atelier.py (voir port3ds/README.md).\n\nSTART pour quitter.\n",
		       DOSSIER);
		while (aptMainLoop())
		{
			hidScanInput();
			if (hidKeysDown() & KEY_START)
				break;
			gspWaitForVBlank();
		}
		C3D_Fini();
		gfxExit();
		return 0;
	}
	memset(&relief, 0, sizeof(relief));
	if (!charger_relief(chemin, &relief))
	{
		printf("Paquet illisible :\n%s\n\nSTART pour quitter.\n", chemin);
		while (aptMainLoop())
		{
			hidScanInput();
			if (hidKeysDown() & KEY_START)
				break;
			gspWaitForVBlank();
		}
		C3D_Fini();
		gfxExit();
		return 0;
	}
	convergence = relief.e.z_convergence;
	if (relief.nb_triangles)
	{
		/* start at the centre of the walkmesh when it is on the floor, else at the centre of its first
		 * triangle */
		int k, t, v;
		float z;
		for (k = 0; k < 3; k++)
		{
			float somme = 0;
			for (t = 0; t < relief.nb_triangles; t++)
				for (v = 0; v < 3; v++)
					somme += relief.triangles[t][v][k];
			pied[k] = somme / (3.0f * relief.nb_triangles);
		}
		if (sol(&relief, pied[0], pied[1], &z))
			pied[2] = z;
		else
			for (k = 0; k < 3; k++)
				pied[k] = (relief.triangles[0][0][k] + relief.triangles[0][1][k] + relief.triangles[0][2][k]) / 3.0f;
	}
	else
		temoin = 0;
	xmin = relief.e.ox + ECRAN_L / 2;
	xmax = relief.e.ox + relief.e.tex_l - ECRAN_L / 2;
	ymin = relief.e.oy + ECRAN_H / 2;
	ymax = relief.e.oy + relief.e.tex_h - ECRAN_H / 2;
	if (xmin > xmax)
		xmin = xmax = relief.e.ox + relief.e.tex_l / 2;
	if (ymin > ymax)
		ymin = ymax = relief.e.oy + relief.e.tex_h / 2;

	gauche = C3D_RenderTargetCreate(ECRAN_H, ECRAN_L, GPU_RB_RGBA8, GPU_RB_DEPTH24_STENCIL8);
	C3D_RenderTargetSetOutput(gauche, GFX_TOP, GFX_LEFT, DISPLAY_TRANSFER_FLAGS);
	droite = C3D_RenderTargetCreate(ECRAN_H, ECRAN_L, GPU_RB_RGBA8, GPU_RB_DEPTH24_STENCIL8);
	C3D_RenderTargetSetOutput(droite, GFX_TOP, GFX_RIGHT, DISPLAY_TRANSFER_FLAGS);
	preparer_rendu();

	while (aptMainLoop())
	{
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
		hidCircleRead(&pad);
		if (temoin)
		{
			/* Walk on the walkmesh: the pad moves the character along the screen's right and forward axes,
			 * projected on the ground; a step that leaves the walkmesh is refused, like a blocked edge. */
			float dx = pad.dx / 156.0f, dy = pad.dy / 156.0f, nx, ny, nz, avant[2], droite[2], n;
			droite[0] = relief.axes[0][0];
			droite[1] = relief.axes[0][1];
			avant[0] = relief.axes[2][0];
			avant[1] = relief.axes[2][1];
			n = sqrtf(droite[0] * droite[0] + droite[1] * droite[1]);
			if (n > 0)
				droite[0] /= n, droite[1] /= n;
			n = sqrtf(avant[0] * avant[0] + avant[1] * avant[1]);
			if (n > 0)
				avant[0] /= n, avant[1] /= n;
			nx = pied[0] + 12.0f * (dx * droite[0] + dy * avant[0]);
			ny = pied[1] + 12.0f * (dx * droite[1] + dy * avant[1]);
			if ((dx != 0 || dy != 0) && sol(&relief, nx, ny, &nz))
			{
				pied[0] = nx;
				pied[1] = ny;
				pied[2] = nz;
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
			temoin = !temoin && relief.nb_triangles;
		if (tenu & KEY_R)
			convergence *= 1.02f;
		if (tenu & KEY_L)
			convergence /= 1.02f;
		if (temoin)
		{
			float px, py;
			placer_temoin(&relief, pied, &px, &py);
			/* the view follows the character, like the field camera scroll */
			cx = px + decal_x;
			cy = py - 40.0f + decal_y;
		}
		else
		{
			cx = decal_x;
			cy = decal_y;
		}
		cx = cx < xmin ? xmin : (cx > xmax ? xmax : cx);
		cy = cy < ymin ? ymin : (cy > ymax ? ymax : cy);

		curseur = osGet3DSliderState();
		actif = curseur > 0.01f;
		k = actif ? curseur * ECART_STEREO * 0.5f : 0.0f;
		vecteur_oeil(-k, convergence, oeil[0]); /* left eye */
		vecteur_oeil(k, convergence, oeil[1]);  /* right eye: far content shifts right */

		C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
		C3D_RenderTargetClear(gauche, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
		C3D_FrameDrawOn(gauche);
		dessiner(&relief, cx, cy, oeil[0], temoin);
		if (actif)
		{
			C3D_RenderTargetClear(droite, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
			C3D_FrameDrawOn(droite);
			dessiner(&relief, cx, cy, oeil[1], temoin);
		}
		C3D_FrameEnd(0);

		maintenant = osGetTime();
		if (dernier)
			ms = ms * 0.9f + (float)(maintenant - dernier) * 0.1f;
		dernier = maintenant;
		if (stats)
		{
			printf("\x1b[4;0H%s  %u sommets, %lu triangles      \n", relief.e.nom, relief.e.nb_sommets,
			       (unsigned long)(relief.e.nb_indices / 3));
			printf("image : %5.1f ms (%4.1f i/s)        \n", ms, ms > 0 ? 1000.0f / ms : 0.0f);
			printf("curseur 3D : %3.0f %%  ecart : %4.1f px    \n", curseur * 100.0f, 2 * k);
			printf("convergence z : %6.0f (L / R)       \n", convergence);
			printf("vue : %5.0f, %5.0f (pad)          \n", cx, cy);
			printf("temoin : %6.0f %6.0f %5.0f (ZR)  \n", pied[0], pied[1], pied[2]);
			printf("cartes d'occlusion : %u            \n", relief.nb_cartes);
			printf("GPU %4.1f %%  CPU %4.1f %%            \n", C3D_GetDrawingTime() * 6.0f,
			       C3D_GetProcessingTime() * 6.0f);
			printf("\nSELECT stats  ZR temoin  START quitter\n");
		}
	}

	C3D_TexDelete(&relief.texture);
	C3D_TexDelete(&relief.masque);
	linearFree(relief.cartes);
	linearFree(relief.idx_cartes);
	linearFree(relief.temoin);
	linearFree(relief.idx_temoin);
	free(relief.triangles);
	linearFree(relief.sommets);
	linearFree(relief.indices);
	shaderProgramFree(&s_programme);
	DVLB_Free(s_dvlb);
	C3D_RenderTargetDelete(gauche);
	C3D_RenderTargetDelete(droite);
	C3D_Fini();
	gfxExit();
	return 0;
}
