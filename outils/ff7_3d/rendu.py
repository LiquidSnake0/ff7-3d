"""Rendu logiciel d'un personnage cuit sur le décor composé, pour contrôler l'atelier sur PC.

Même chaîne que la 3DS (port3ds/source/main.c) : rotation autour de z par la direction, pose sur le sol,
caméra du terrain, projection du GTE ; tri des triangles du plus loin au plus proche (peintre), sans
l'occlusion des tuiles.
"""
import math

import numpy as np

from . import camera


def direction_vers(dx, dy):
    """Octet de direction (256 pas par tour) qui fait regarder le personnage vers (dx, dy) du monde.

    À la direction 0, le personnage regarde vers -y ; la rotation autour de z tourne ce regard."""
    a = math.atan2(dx, -dy)
    return int(round(a * 256.0 / (2.0 * math.pi))) & 0xFF


def poser(cuisson, anim, image, position, direction):
    """Sommets du personnage dans le monde pour une image d'animation."""
    images = cuisson.animations[anim]
    p = images[image % len(images)].astype(np.float64)
    a = (direction & 0xFF) * 2.0 * math.pi / 256.0
    c, s = math.cos(a), math.sin(a)
    x = p[:, 0] * c - p[:, 1] * s
    y = p[:, 0] * s + p[:, 1] * c
    return np.stack([x, y, p[:, 2]], axis=1) + np.asarray(position, float)


def dessiner(image_rgb, champ, origine, cuisson, position, direction=0, anim=0, num_image=0):
    """Dessine le personnage sur une image PIL (mode RGB) du décor composé ; rend sa boîte à l'écran."""
    from PIL import ImageDraw
    monde = poser(cuisson, anim, num_image, position, direction)
    ecran, z = camera.projeter(champ.camera, monde)
    ecran = ecran - np.asarray(origine, float)
    dr = ImageDraw.Draw(image_rgb)
    ordre = []
    for i0, i1, i2, c0, c1, c2 in cuisson.triangles:
        ordre.append(((z[i0] + z[i1] + z[i2]) / 3.0, (i0, i1, i2), tuple(int(sum(v) / 3) for v in zip(c0, c1, c2))))
    ordre.sort(key=lambda t: -t[0])
    for _z, idx, couleur in ordre:
        dr.polygon([tuple(ecran[i]) for i in idx], fill=couleur)
    return ecran.min(0), ecran.max(0)
