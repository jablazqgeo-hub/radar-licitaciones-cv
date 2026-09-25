# Radar de Licitaciones · Comunitat Valenciana

Prototipo para localizar y clasificar licitaciones relacionadas con:

1. Planificación urbana
2. Planificación territorial/urbanística
3. Movilidad
4. Turismo territorial
5. Infraestructura verde
6. Cambio climático
7. Paisaje
8. Accesibilidad
9. Smart City
10. Desarrollo local

## Instalación sencilla

Necesitas Python 3.10 o superior.

### Windows

1. Descomprime esta carpeta.
2. Abre PowerShell o Símbolo del sistema dentro de la carpeta.
3. Ejecuta:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Se abrirá una página local en el navegador, normalmente en `http://localhost:8501`.

## Uso básico

1. En **Fuente**, deja marcada `Descarga oficial mensual`.
2. Selecciona año y mes.
3. Pulsa **Descargar y analizar**.
4. Usa los filtros de provincia, familia y relevancia mínima.
5. Escribe una palabra en **Buscar texto** si quieres restringir todavía más (por ejemplo `PMUS`, `PSTD`, `Agenda Urbana`).
6. Pulsa **Exportar resultados a CSV** para trabajar las oportunidades en Excel.

Si la descarga automática fallase por una restricción temporal del servidor oficial, descarga manualmente los ZIP de Datos Abiertos de PLACSP y utiliza la opción **Subir ZIP oficial**.

## Cómo puntúa

El sistema no se limita a una única palabra. Busca vocabulario especializado de las 10 familias y añade puntos cuando detecta expresiones propias de planes, estrategias, estudios, consultoría, redacción o asistencia técnica. También usa CPV como señal secundaria y penaliza algunos contratos que parecen ser únicamente de ejecución de obra o suministro.

La puntuación (0-100) sirve para ordenar resultados; no sustituye la revisión humana del expediente.

## Fuentes oficiales configuradas

El programa intenta descargar los dos conjuntos mensuales necesarios para mejorar cobertura:

- Licitaciones publicadas en perfiles alojados en la Plataforma de Contratación del Sector Público, excluyendo contratos menores.
- Licitaciones publicadas mediante mecanismos de agregación, excluyendo contratos menores.

Los datos oficiales pueden contener múltiples actualizaciones del mismo expediente. El programa conserva la versión más reciente que encuentra.

## Personalizar categorías

Las palabras clave están en `config.py`. Puedes añadir o quitar términos sin modificar el resto de la aplicación.

Ejemplo:

```python
"Movilidad": {
    "weight": 1.0,
    "keywords": ["pmus", "plan de movilidad urbana sostenible", "..."],
}
```

## Próximas mejoras recomendadas

- Catálogo completo de municipios y organismos locales CV para un filtro geográfico más preciso.
- Detección de estado: abierta / cerrada / adjudicada.
- Extracción fiable de importe y plazo desde todas las variantes CODICE.
- Histórico y alertas de nuevas oportunidades.
- Clasificación semántica con IA además de palabras clave.
- Ficha de oportunidad con resumen de pliegos y requisitos de solvencia.
