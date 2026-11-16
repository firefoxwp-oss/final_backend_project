# Modelos preentrenados

Modelos de aprendizaje automático que usa el procesamiento. Se cargan desde
esta carpeta, así que el sistema funciona sin conexión a internet.

| Carpeta | Modelo | Uso |
|---|---|---|
| `demucs/` | Demucs v4 (htdemucs) | Separación de la voz (modelo principal) |
| `spleeter/` | Spleeter 2stems | Separación de la voz (respaldo) |
| `whisperx/` | Whisper large-v2 y wav2vec2 en español | Transcripción y alineación de la letra |

Cada modelo tiene:

- `modelo/`: los pesos preentrenados.
- `dataset/`: MUSDB18 (fragmentos de 7 s, licencia CC BY 4.0), solo en Demucs
  y Spleeter.
- `entrenamiento/`: cuaderno de fine-tuning para Google Colab.

Los pesos y el dataset no se guardan en el repositorio; se descargan con:

```
python pretrained_models/descargar_modelos.py --dataset
```
