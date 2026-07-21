"""APEX lib — módulos del núcleo.

Existe para que los hooks puedan hacer `from lib.hook_metrics import ...`
con la raíz del repo en sys.path. Los módulos también se importan sueltos
(con `lib/` en el path), así que este fichero no debe importar nada.
"""
