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
 * Controls: circle pad / D-pad scroll, L / R move the convergence plane, SELECT toggles the frame stats,
 * START quits.
 */
#include <3ds.h>
#include <citro3d.h>
#include <dirent.h>
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
} Relief;

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

static int charger_relief(const char* chemin, Relief* r)
{
	FILE* f = fopen(chemin, "rb");
	size_t octets_tex, octets_sommets, octets_indices;
	void* tampon;
	if (!f)
		return 0;
	if (fread(&r->e, sizeof(r->e), 1, f) != 1 || memcmp(r->e.magie, "F3D1", 4) != 0 || r->e.version != 1)
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
	fclose(f);
	return 1;

echec:
	fclose(f);
	return 0;
}

static void preparer_rendu(Relief* r)
{
	C3D_AttrInfo* attr;
	C3D_BufInfo* buf;
	C3D_TexEnv* env;

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

	buf = C3D_GetBufInfo();
	BufInfo_Init(buf);
	BufInfo_Add(buf, r->sommets, 5 * sizeof(float), 2, 0x10);

	C3D_TexBind(0, &r->texture);
	env = C3D_GetTexEnv(0);
	C3D_TexEnvInit(env);
	C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, 0, 0);
	C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);

	C3D_CullFace(GPU_CULL_NONE);
	/* Mtx_OrthoTilt maps a larger vertex z to a smaller stored depth: LEQUAL with the clear at the far end
	 * (CTR-3D, n3ds_backend.c). */
	C3D_DepthTest(true, GPU_LEQUAL, GPU_WRITE_ALL);
}

static void dessiner(Relief* r, float cx, float cy, const float stereo[4])
{
	C3D_Mtx projection;
	/* The visible window, in PS1 screen pixels; y grows downwards like on the PS1. */
	Mtx_OrthoTilt(&projection, cx - ECRAN_L / 2, cx + ECRAN_L / 2, cy + ECRAN_H / 2, cy - ECRAN_H / 2, -32769.0f,
	              32769.0f, true);
	C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &projection);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uH, (float)r->e.zoom, 1.0f / (float)r->e.zoom, 0.0f, 0.0f);
	C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uStereo, stereo[0], stereo[1], stereo[2], stereo[3]);
	C3D_DrawElements(GPU_TRIANGLES, (int)r->e.nb_indices, C3D_UNSIGNED_SHORT, r->indices);
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
	preparer_rendu(&relief);

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
		cx += pad.dx / 40.0f + ((tenu & KEY_DRIGHT) ? 2 : 0) - ((tenu & KEY_DLEFT) ? 2 : 0);
		cy -= pad.dy / 40.0f;
		cy += ((tenu & KEY_DDOWN) ? 2 : 0) - ((tenu & KEY_DUP) ? 2 : 0);
		cx = cx < xmin ? xmin : (cx > xmax ? xmax : cx);
		cy = cy < ymin ? ymin : (cy > ymax ? ymax : cy);
		if (tenu & KEY_R)
			convergence *= 1.02f;
		if (tenu & KEY_L)
			convergence /= 1.02f;

		curseur = osGet3DSliderState();
		actif = curseur > 0.01f;
		k = actif ? curseur * ECART_STEREO * 0.5f : 0.0f;
		vecteur_oeil(-k, convergence, oeil[0]); /* left eye */
		vecteur_oeil(k, convergence, oeil[1]);  /* right eye: far content shifts right */

		C3D_FrameBegin(C3D_FRAME_SYNCDRAW);
		C3D_RenderTargetClear(gauche, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
		C3D_FrameDrawOn(gauche);
		dessiner(&relief, cx, cy, oeil[0]);
		if (actif)
		{
			C3D_RenderTargetClear(droite, C3D_CLEAR_ALL, 0x000000FF, 0x00FFFFFF);
			C3D_FrameDrawOn(droite);
			dessiner(&relief, cx, cy, oeil[1]);
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
			printf("GPU %4.1f %%  CPU %4.1f %%            \n", C3D_GetDrawingTime() * 6.0f,
			       C3D_GetProcessingTime() * 6.0f);
			printf("\nSELECT : stats   START : quitter\n");
		}
	}

	C3D_TexDelete(&relief.texture);
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
