/*
 * ff7-3d -- the player's character (Cloud) on the New 3DS.
 * Copyright (C) 2026 Selim
 *
 * This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
 * General Public License as published by the Free Software Foundation, either version 3 of the License, or (at
 * your option) any later version. See LICENSE at the root of the repository.
 */
#pragma once

#include <3ds.h>
#include <stdio.h>

#define PERSONNAGE_ANIMS_MAX 4

/* What the CPU needs of the field camera: c = R v + t, sx = H cx / cz, sy = H cy / cz. */
typedef struct
{
	float axes[3][3];
	float trans[3];
	float zoom;
} CameraTerrain;

/*
 * A character baked by the workshop (outils/ff7_3d/modele.py, package section "PERS"): every frame of every
 * animation as world-space vertices with the feet at the origin, looking towards -y. The 3DS turns it around z,
 * stands it on the floor and projects it with the field camera, on the CPU (about 300 vertices), then draws the
 * triangles with their PS1 colours through source/modele.v.pica.
 */
typedef struct
{
	u16 nb_sommets;
	u16 nb_triangles;
	u8 nb_anims;
	float hauteur;
	u16* sommets_tri;                      /* nb_triangles x 3 vertex indices */
	u8* couleurs;                          /* nb_triangles x 3 x rgb */
	u16 nb_images[PERSONNAGE_ANIMS_MAX];
	float* images[PERSONNAGE_ANIMS_MAX];   /* nb_images x nb_sommets x xyz */
	float* ecran;                          /* nb_sommets x (sx, sy, z), this frame */
	float* tampon;                         /* linear memory: nb_triangles x 3 x (sx, sy, z, r, g, b, a) */
} Personnage;

/* Reads the "PERS" section. 1: a character is there, 0: the section is empty, -1: unreadable. */
int personnage_charger(FILE* f, Personnage* p);

/*
 * Poses one frame: the animation `anim` at frame `image` (fractional frames round down), turned by `angle` (radians,
 * 0 = looking towards -y, positive = counter-clockwise seen from above), the feet at `pied` (world). Fills the
 * vertex buffer and returns the screen position of the feet and the top of the head.
 */
void personnage_poser(Personnage* p, const CameraTerrain* cam, const float pied[3], float angle, int anim, float image,
                      float* sx_pied, float* sy_pied, float* sy_tete, float* z_pied);

void personnage_liberer(Personnage* p);
