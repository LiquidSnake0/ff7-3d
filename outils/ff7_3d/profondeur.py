"""Profondeur du décor : modèle monoculaire (Depth Anything V2 Small, Apache-2.0) recalé sur les repères.

Le modèle et ses poids ne sont pas dans le dépôt : le joueur les installe chez lui (voir docs/ff7-3d/atelier.md).
    FF7_3D_DAV2   dossier du code officiel (github.com/DepthAnything/Depth-Anything-V2)
    FF7_3D_POIDS  fichier depth_anything_v2_vits.pth (huggingface.co/depth-anything/Depth-Anything-V2-Small)

Le modèle donne une disparité relative d (plus grande = plus proche). On cherche a, b tels que
1/z ≈ a·d + b sur les repères exacts (sol du walkmesh, tuiles de couche 2), par moindres carrés pondérés
et robustes, puis on aligne chaque tuile de couche 2 sur sa profondeur d'origine en gardant son relief.
"""
import os
import sys

import numpy as np

DAV2 = os.environ.get("FF7_3D_DAV2", os.path.expanduser("~/opt/ff7-3d/dav2"))
POIDS = os.environ.get("FF7_3D_POIDS", os.path.expanduser("~/opt/ff7-3d/depth_anything_v2_vits.pth"))
SHA256_POIDS = "715fade13be8f229f8a70cc02066f656f2423a59effd0579197bbf57860e1378"


def disparite(image_rgb, taille_entree=518):
    """Disparité relative du modèle, à la résolution de l'image (H x W, float32)."""
    import torch
    sys.path.insert(0, DAV2)
    from depth_anything_v2.dpt import DepthAnythingV2

    modele = DepthAnythingV2(encoder="vits", features=64, out_channels=[48, 96, 192, 384])
    modele.load_state_dict(torch.load(POIDS, map_location="cpu"))
    modele.eval()
    bgr = np.ascontiguousarray(image_rgb[..., ::-1])
    with torch.no_grad():
        d = modele.infer_image(bgr, taille_entree)
    return np.asarray(d, dtype=np.float32)


def ajuster(d, z_reperes, poids, iterations=5, seuil=2.5):
    """Ajuste 1/z = a·d + b sur les pixels repères ; renvoie (a, b, écart relatif médian)."""
    m = np.isfinite(z_reperes) & (poids > 0)
    x = d[m].astype(np.float64)
    y = 1.0 / z_reperes[m]
    w = poids[m].astype(np.float64)
    garde = np.ones_like(x, dtype=bool)
    a = b = 0.0
    for _ in range(iterations):
        sw = np.sqrt(w[garde])
        A = np.stack([x[garde], np.ones(garde.sum())], axis=1) * sw[:, None]
        a, b = np.linalg.lstsq(A, y[garde] * sw, rcond=None)[0]
        residu = np.abs(a * x + b - y)
        echelle = np.median(residu[garde]) * 1.4826 + 1e-12
        garde = residu < seuil * echelle
    z_ajuste = 1.0 / np.maximum(a * x + b, 1e-9)
    ecart = np.median(np.abs(z_ajuste - z_reperes[m]) / z_reperes[m])
    return a, b, float(ecart)


def z_depuis_disparite(d, a, b, z_min, z_max):
    inv = a * d.astype(np.float64) + b
    z = np.where(inv > 0, 1.0 / np.maximum(inv, 1e-12), z_max)
    return np.clip(z, z_min, z_max)


def recaler(d, reperes, champ, fond_compose, z_max=None):
    """Profondeur d'affichage (H x W, z caméra) et le rapport du recalage."""
    poids = reperes.poids
    z_reperes = np.where(np.isfinite(reperes.z_sol), reperes.z_sol, reperes.z_tuiles)
    a, b, ecart = ajuster(d, z_reperes, poids)
    finis = z_reperes[np.isfinite(z_reperes)]
    z_min = max(1.0, float(finis.min()) * 0.5)
    z_max = z_max or float(finis.max()) * 4.0
    z = z_depuis_disparite(d, a, b, z_min, z_max)

    # le sol est connu exactement : on le reprend tel quel
    sol = np.isfinite(reperes.z_sol)
    z[sol] = reperes.z_sol[sol]

    # chaque tuile de couche 2 garde son relief mais se recale sur sa profondeur d'origine (4 · ID)
    ox, oy = fond_compose.origine
    desaccords = 0
    for t in champ.tuiles:
        if t.couche != 2 or t.profondeur >= 4095 - 16 or t.profondeur < 16:
            continue
        px, py = t.x - ox, t.y - oy
        zone = (slice(py, py + t.taille), slice(px, px + t.taille))
        texels = (fond_compose.couche[zone] == 2) & (fond_compose.profondeur_id[zone] == t.profondeur)
        if not texels.any():
            continue
        cible = 4.0 * t.profondeur
        bloc = z[zone]
        median = np.median(bloc[texels])
        # Les ID de couche 2 servent d'abord au tri : quand ils contredisent nettement le modèle et le
        # sol (MD1STIN : ID 294 pour un morceau de train que tout place vers z = 610), on garde le
        # modèle, sinon on fabriquerait des marches dans le relief. L'occlusion, elle, suit toujours l'ID.
        if abs(np.log(cible / median)) > np.log(1.3):
            desaccords += 1
            continue
        bloc[texels] = np.clip(bloc[texels] + (cible - median), z_min, z_max)
    rapport = {"a": float(a), "b": float(b), "ecart_median_relatif": ecart,
               "z_min": z_min, "z_max": z_max, "pixels_reperes": int(np.isfinite(z_reperes).sum()),
               "tuiles_en_desaccord": desaccords}
    return z.astype(np.float32), rapport
