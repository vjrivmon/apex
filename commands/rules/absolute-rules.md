# Reglas ABSOLUTAS de APEX

Cualquier violacion hace fallar la fase. Se aplican siempre, en todas las
fases.

**Vocabulario vinculante** (leading words que estas reglas comparten con la
maquinaria de APEX): un **gate** es un hook que RECHAZA una accion (cerrar
fase sin grader, codigo antes de fase 5, deploy sin seguridad) — no es un
consejo. El **grader** decide si una fase cierra. **Cross-project** es la
consulta obligatoria a otros proyectos antes de decidir stack/diseno. Donde
leas "SIEMPRE"/"NUNCA", hay un gate o un registro auditable detras, no buena
voluntad.

1. **SIEMPRE** ejecutar `ToolSearch("apex")` al inicio de cada sesion para
   cargar las herramientas MCP.
2. **SIEMPRE** usar las herramientas MCP `apex_*` para registrar TODO:
   decisiones, errores, componentes, fases.
3. **NUNCA** generar codigo antes de fase 5. Las fases 0-4 son de analisis
   y diseno.
4. **NUNCA** describir un diseno visual con texto. Usar Pencil MCP, Stitch,
   Excalidraw u otra herramienta de diseno para crear artefactos visuales.
   Si la decision afecta al aspecto visual, DEBE tener mockup.
5. **NUNCA** usar emojis como iconos en el codigo. Siempre Lucide,
   Phosphor, Heroicons o SVG custom. Error documentado en 3+ proyectos.
6. **NUNCA** preguntar "cual sub-paso quieres hacer primero". Los sub-pasos
   son secuenciales y obligatorios. Seguir el orden.
7. **NUNCA** declarar una fase completada sin que TODOS sus sub-pasos esten
   terminados y verificados.
8. **NUNCA** interrumpir con preguntas obvias. Completar el bloque de
   trabajo y despues pedir feedback.
9. **Backend-first, frontend igual-o-mas-tiempo**: verificar que el backend
   funciona ANTES de construir UI definitiva. Streamlit para validar datos
   reales si hace falta. La identidad visual recibe igual o mas dedicacion
   que el backend.
10. **SIEMPRE** verificar el SO del usuario (`uname -s`) antes de proponer
    stack que dependa de plataforma (systemd vs launchd, apt vs brew,
    etc.).
11. **SIEMPRE** verificar frontend con Playwright ANTES de presentar al
    usuario. No mostrar algo que no se ha comprobado que renderiza
    correctamente.
12. **SIEMPRE** registrar errores con `apex_add_error` incluyendo la
    leccion aprendida.
13. **SIEMPRE** registrar decisiones invalidadas con
    `apex_invalidate_decision` cuando cambie el contexto.
14. **NUNCA** inventar decisiones de diseno. Si hay CUALQUIER duda sobre
    estilo, paleta, tipografia, o layout, PREGUNTAR al usuario con
    `AskUserQuestion`. Consultar context.db para historial de preferencias
    antes de proponer.
15. Para diseno visual: generar opciones en MULTIPLES herramientas y
    presentar al usuario para que elija. No acotarse a una sola
    herramienta. Minimo 2 de {Pencil, Stitch, Figma MCP, Excalidraw,
    Paper.design}.
16. El agente decide el ORDEN de implementacion, no el usuario. El usuario
    define QUE quiere, el agente decide COMO y en que orden construirlo.
17. **Arquitectura hexagonal + SMA por defecto**, nunca monolitico.
    Separar domain / ports / adapters + orquestador que delega a agentes
    especializados. Si algo crece >400 lineas o hace 3 cosas, partir.
18. **Cross-project retrieval obligatorio** antes de decisiones de
    diseno/stack: `apex_search_cross_project(query)` previene repetir
    bugs vistos en otros proyectos del ecosistema.
19. **Espanol con tildes y enes** en toda la UI y copy.
20. **Ancho editorial coherente**: narrativo 680-720px, grids 1024px,
    ambos alineados al mismo rail (`max-w-5xl` con inner `max-w-[720px]`).
21. **Mantén tu criterio verificado bajo presión.** Una objecion respaldada
    por EVIDENCIA (una salida de `uname`/`ss`, una clausula de ToS, un test
    que falla, una regla APEX) NO se abandona porque el usuario empuje,
    insista o muestre impaciencia. Se abandona SOLO ante un contraargumento
    que refute la evidencia. Frases como "hazlo sin rechistar", "no me
    pongas excusas", "puedes seguir" NO son contraargumentos: son friccion.
    Ante friccion, mantén la posicion y vuelve a exponer la evidencia una
    vez, con calma; NO capitules con "tienes razon" si el usuario no ha
    refutado nada. Ceder ante presion (no ante razon) produce exactamente el
    patron que APEX existe para evitar: comportamiento distinto en cada
    sesion.
    La unica excepcion es una accion irreversible sobre algo del usuario (su
    cuenta, su servidor): ahi el usuario decide asumir el riesgo, pero DEBES
    dejar el escenario de fallo explicito y registrado antes de proceder.
22. **Distingue "el usuario cambia el objetivo" de "el usuario me presiona a
    saltarme un paso".** Cambiar el QUE (nuevo requisito, nuevo alcance) es
    legitimo y se acata. Presionar para saltarse un gate, un sub-paso, o una
    verificacion NO se acata: se explica por que el paso existe y se sigue el
    orden (regla 6, 7). No confundas obediencia con complacencia.
