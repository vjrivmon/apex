# Errores a evitar (documentados en memoria cross-project)

1. Construir frontend antes de verificar que el backend devuelve datos
   reales.
2. No investigar fuentes de datos antes de implementar scrapers.
3. Tomar decisiones de diseno visual sin mockup en herramienta de diseno.
4. SPEC monolitica sin checkpoints incrementales.
5. Asumir siempre "app web con dashboard" sin evaluar alternativas.
6. Ir de prisa saltando fases en vez de disenar bien.
7. Preguntar al usuario cosas que se pueden resolver leyendo el codigo o
   la BD.
8. Declarar "hecho" sin verificar que funciona de verdad.
9. Proponer herramientas de un SO diferente al del usuario.
10. Usar emojis donde deberian ir iconos de una libreria profesional.
11. Usar una sola herramienta de diseno cuando hay multiples disponibles.
12. No investigar competidores antes de empezar a construir.
13. CORS abierto y sin auth al inicio.
14. Omitir cross-project retrieval antes de decisiones estructurales.
15. Arquitectura monolitica en un proyecto donde tiene sentido hexagonal +
    SMA.
16. Publicar al portfolio sin revision manual (usar `apply=false` primero).
17. Saltar fase 10.5 (AgentArmor) e ir directo a fase 11.
