# Arquitectura del Sistema

## Componentes principales
1. **Ingesta de datos**: Simulación y recepción de eventos en tiempo real.
2. **Análisis de sexo aparente**: Inferencia a partir de dorsales o imágenes.
3. **Interpretación de reglas**: Procesamiento de texto reglamentario para aplicar condiciones automáticas.
4. **Integración y flujo lógico**: Orquestación general del sistema y evaluación.

## Diagrama (esquemático)
[Simulador de Eventos] → [Análisis de Datos] → [Reglas Aplicadas] → [Resultados]

## Tecnologías propuestas
- Python
- OpenCV o librerías de visión (si hay análisis de imágenes)
- NLP con spaCy o transformers
- Posible API REST con FastAPI
