/*
 * ff7-3d -- the player's character (Cloud) on the New 3DS.
 * Copyright (C) 2026 Selim
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
 * General Public License as published by the Free Software Foundation, either version 3 of the License, or (at
 * your option) any later version. See LICENSE at the root of the repository.
 */
#include "personnage.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

typedef struct
{
	char magie[4];
	u16 nb_sommets;
	u16 nb_triangles;
	u8 nb_anims;
	u8 bourrage;
	u16 bourrage2;
	float hauteur;
} __attribute__((packed)) EnTetePersonnage;

typedef struct
{
	u16 i[3];
	u8 rgb[9];
	u8 bourrage;
} __attribute__((packed)) TrianglePersonnage;

int personnage_charger(FILE* f, Personnage* p)
{
	EnTetePersonnage e;
	u16 t;
	int a;
	memset(p, 0, sizeof(*p));
	if (fread(&e, sizeof(e), 1, f) != 1 || memcmp(e.magie, "PERS", 4) != 0)
		return -1;
	if (!e.nb_sommets || !e.nb_triangles || !e.nb_anims)
		return 0;
	p->nb_sommets = e.nb_sommets;
	p->nb_triangles = e.nb_triangles;
	p->nb_anims = e.nb_anims > PERSONNAGE_ANIMS_MAX ? PERSONNAGE_ANIMS_MAX : e.nb_anims;
	p->hauteur = e.hauteur;
	p->sommets_tri = malloc((size_t)e.nb_triangles * 3 * sizeof(u16));
	p->couleurs = malloc((size_t)e.nb_triangles * 9);
	p->ecran = malloc((size_t)e.nb_sommets * 3 * sizeof(float));
	p->tampon = linearAlloc((size_t)e.nb_triangles * 3 * 7 * sizeof(float));
	if (!p->sommets_tri || !p->couleurs || !p->ecran || !p->tampon)
		return -1;
	for (t = 0; t < e.nb_triangles; t++)
	{
		TrianglePersonnage tr;
		if (fread(&tr, sizeof(tr), 1, f) != 1)
			return -1;
		memcpy(p->sommets_tri + t * 3, tr.i, sizeof(tr.i));
		memcpy(p->couleurs + t * 9, tr.rgb, 9);
		if (tr.i[0] >= e.nb_sommets || tr.i[1] >= e.nb_sommets || tr.i[2] >= e.nb_sommets)
			return -1;
	}
	for (a = 0; a < e.nb_anims; a++)
	{
		u16 n[2];
		size_t octets;
		float* images;
		if (fread(n, sizeof(n), 1, f) != 1 || n[0] == 0)
			return -1;
		octets = (size_t)n[0] * e.nb_sommets * 3 * sizeof(float);
		images = malloc(octets);
		if (!images || fread(images, 1, octets, f) != octets)
		{
			free(images);
			return -1;
		}
		if (a < PERSONNAGE_ANIMS_MAX)
		{
			p->nb_images[a] = n[0];
			p->images[a] = images;
		}
		else
			free(images);
	}
	return 1;
}

void personnage_poser(Personnage* p, const CameraTerrain* cam, const float pied[3], float angle, int anim, float image,
                      float* sx_pied, float* sy_pied, float* sy_tete, float* z_pied)
{
	const float* src;
	float c = cosf(angle), s = sinf(angle);
	int i, n, k;
	float haut = 1e9f;
	if (anim < 0 || anim >= p->nb_anims)
		anim = 0;
	n = (int)image;
	n %= p->nb_images[anim];
	if (n < 0)
		n += p->nb_images[anim];
	src = p->images[anim] + (size_t)n * p->nb_sommets * 3;
	for (i = 0; i < p->nb_sommets; i++)
	{
		float w[3], cc[3];
		w[0] = pied[0] + src[i * 3 + 0] * c - src[i * 3 + 1] * s;
		w[1] = pied[1] + src[i * 3 + 0] * s + src[i * 3 + 1] * c;
		w[2] = pied[2] + src[i * 3 + 2];
		for (k = 0; k < 3; k++)
			cc[k] = cam->axes[k][0] * w[0] + cam->axes[k][1] * w[1] + cam->axes[k][2] * w[2] + cam->trans[k];
		if (cc[2] < 1.0f)
			cc[2] = 1.0f;
		p->ecran[i * 3 + 0] = cam->zoom * cc[0] / cc[2];
		p->ecran[i * 3 + 1] = cam->zoom * cc[1] / cc[2];
		p->ecran[i * 3 + 2] = cc[2];
		if (p->ecran[i * 3 + 1] < haut)
			haut = p->ecran[i * 3 + 1];
	}
	for (i = 0; i < p->nb_triangles * 3; i++)
	{
		const float* e = p->ecran + p->sommets_tri[i] * 3;
		float* v = p->tampon + (size_t)i * 7;
		const u8* rgb = p->couleurs + i * 3;
		v[0] = e[0];
		v[1] = e[1];
		v[2] = e[2];
		v[3] = rgb[0] / 255.0f;
		v[4] = rgb[1] / 255.0f;
		v[5] = rgb[2] / 255.0f;
		v[6] = 1.0f;
	}
	GSPGPU_FlushDataCache(p->tampon, (size_t)p->nb_triangles * 3 * 7 * sizeof(float));
	{
		float cc[3];
		for (k = 0; k < 3; k++)
			cc[k] = cam->axes[k][0] * pied[0] + cam->axes[k][1] * pied[1] + cam->axes[k][2] * pied[2] + cam->trans[k];
		if (cc[2] < 1.0f)
			cc[2] = 1.0f;
		*sx_pied = cam->zoom * cc[0] / cc[2];
		*sy_pied = cam->zoom * cc[1] / cc[2];
		*z_pied = cc[2];
	}
	*sy_tete = haut;
}

void personnage_liberer(Personnage* p)
{
	int a;
	free(p->sommets_tri);
	free(p->couleurs);
	free(p->ecran);
	if (p->tampon)
		linearFree(p->tampon);
	for (a = 0; a < PERSONNAGE_ANIMS_MAX; a++)
		free(p->images[a]);
	memset(p, 0, sizeof(*p));
}
