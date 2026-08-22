# Source evidence images

This directory is reserved for **source facsimiles**: screenshots, scans, photographs, maps, charts or figures copied from evidentiary sources when repository storage/reuse is justified.

Every committed source image must have a sibling metadata JSON record conforming to `../../schemas/evidence-image-metadata.schema.json`.

Minimum metadata:

- source URL;
- capture timestamp;
- SHA-256 of the exact stored asset bytes;
- storage/reuse or licensing basis;
- the dossier propositions/sections it supports;
- exact transformation history (`none`, crop, redaction, etc.).

A source image is evidence only to the extent supported by its provenance and the accompanying dossier text. Cropping, annotation and visual prominence do not increase evidentiary weight.

Do not place generated illustrations, reconstructed scenes or decorative imagery here. Derived repository charts and evidence diagrams belong under `../assets/generated/`.
