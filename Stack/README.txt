**Python**

Es el estándar en NLP, IA y LLMs. Todas las grandes librerías como OpenAI, HuggingFace, LangChain, FAISS, etc., están pensadas primero para Python. Tiene una sintaxis clara y productividad alta, comunidad amplia y buen soporte para prototipado rápido y despliegue.


----------------------------------------

**FastAPI**

Rápido, asíncrono, y moderno. Ideal para construir tanto APIs REST como WebSockets en tiempo real. Soporte nativo para WebSockets (@app.websocket), validación de datos automática con Pydantic, muy compatible con Docker y despliegues serverless.


----------------------------------------

**OpenAI API o DeepSeek-LLM**

No necesitas entrenar un LLM desde cero. Estos modelos ofrecen rendimiento de SOTA (estado del arte) y se integran vía API. Fiables, rápidos y actualizados, compatible con RAG y uso profesional, ahorra mucho tiempo de infraestructura y entrenamiento.


-----------------------------------------

**LangChain + FAISS / Weaviate**

Necesitas buscar en reglamentos deportivos, documentos y contexto para que el LLM sea útil en tiempo real. 

LangChain te da una arquitectura modular para pipelines RAG. 
FAISS: rápido, local y sencillo para empezar.
Weaviate: vector store avanzado con features como filtros y metadatos.


------------------------------------------

**WebSockets (con FastAPI)**

Copernico genera flujos de eventos en tiempo real desde cronómetros. Necesitas recibir y actuar sobre esos datos inmediatamente.

WebSockets permiten conexión persistente y bidireccional. Soportado de forma nativa en FastAPI. Fácil de simular en entorno de desarrollo.


------------------------------------------

**PostgreSQL o SQLite (con SQLModel)**

Para implementar RLHF, necesitas guardar los resultados y opiniones humanas sobre las respuestas del agente.

SQLModel (de los creadores de FastAPI) es moderno y simple.
SQLite para desarrollo local, PostgreSQL para producción.

Se puede integrar con dashboards, análisis y RL.

-------------------------------------------

**Docker – Entorno reproducible**

Asegura que tu entorno local sea igual al de producción. Evita “en mi máquina sí funciona”.

Aislamiento completo del entorno.
Fácil despliegue en la nube.
Compatible con funciones serverless si se decide empaquetarlo.


