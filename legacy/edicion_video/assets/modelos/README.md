# Modelos de caras (OpenCV Zoo, licencia MIT)

| Archivo | Para qué | En el repo |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | Detección de caras (encuadre, CLIP-38) | Sí (232 KB) |
| `face_recognition_sface_2021dec.onnx` | Reconocer a la persona del clip (CLIP-40) | **No** (37 MB): descargarlo |

Descarga de SFace (desde `legacy/`):

```bash
curl -L -o edicion_video/assets/modelos/face_recognition_sface_2021dec.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
```

Sin SFace el encuadre funciona igual que en el S6 (sigue la cara más visible).
