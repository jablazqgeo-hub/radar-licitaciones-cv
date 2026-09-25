CATEGORIES = {
    "Planificación urbana": {
        "keywords": [
            "agenda urbana", "agenda urbana local", "plan de acción de agenda urbana",
            "plan de accion de agenda urbana", "estrategia urbana", "estrategia urbana integrada",
            "plan estratégico de ciudad", "plan estrategico de ciudad", "planificación urbana",
            "planificacion urbana", "desarrollo urbano sostenible", "edusi", "dusi"
        ],
    },
    "Planificación territorial/urbanística": {
        "keywords": [
            "plan general estructural", "pge", "pgou", "planeamiento urbanístico",
            "planeamiento urbanistico", "ordenación del territorio", "ordenacion del territorio",
            "ordenación urbana", "ordenacion urbana", "plan especial", "estudio territorial",
            "plan de acción territorial", "plan de accion territorial", "plan territorial",
            "instrumento de planeamiento", "modificación de planeamiento", "modificacion de planeamiento",
            "plan general", "planeamiento general"
        ],
    },
    "Movilidad": {
        "keywords": [
            "pmus", "plan de movilidad urbana sostenible", "movilidad urbana sostenible",
            "plan de movilidad", "movilidad ciclista", "plan ciclista", "plan ciclable",
            "movilidad peatonal", "plan peatonal", "estudio de tráfico", "estudio de trafico",
            "plan de estacionamiento", "transporte público", "transporte publico",
            "zona de bajas emisiones", "zbe", "movilidad metropolitana"
        ],
    },
    "Turismo territorial": {
        "keywords": [
            "pdti", "destino turístico inteligente", "destino turistico inteligente", "dti",
            "plan director de turismo", "plan estratégico de turismo", "plan estrategico de turismo",
            "planificación turística", "planificacion turistica", "plan de sostenibilidad turística en destino",
            "plan de sostenibilidad turistica en destino", "pstd", "estrategia turística", "estrategia turistica",
            "plan turístico", "plan turistico"
        ],
    },
    "Infraestructura verde": {
        "keywords": [
            "infraestructura verde", "infraestructura verde y azul", "renaturalización", "renaturalizacion",
            "corredor verde", "corredores verdes", "biodiversidad urbana", "conectividad ecológica",
            "conectividad ecologica", "soluciones basadas en la naturaleza", "arbolado urbano"
        ],
    },
    "Cambio climático": {
        "keywords": [
            "paces", "paesc", "plan de acción para el clima", "plan de accion para el clima",
            "plan de acción para el clima y la energía sostenible", "adaptación al cambio climático",
            "adaptacion al cambio climatico", "mitigación del cambio climático", "mitigacion del cambio climatico",
            "neutralidad climática", "neutralidad climatica", "estrategia climática", "estrategia climatica",
            "riesgos climáticos", "riesgos climaticos", "plan climático", "plan climatico"
        ],
    },
    "Paisaje": {
        "keywords": [
            "estudio de paisaje", "integración paisajística", "integracion paisajistica",
            "estudio de integración paisajística", "estudio de integracion paisajistica",
            "catálogo de paisaje", "catalogo de paisaje", "paisaje urbano", "paisaje territorial"
        ],
    },
    "Accesibilidad": {
        "keywords": [
            "plan municipal de accesibilidad", "plan de accesibilidad", "accesibilidad universal",
            "itinerarios accesibles", "diagnóstico de accesibilidad", "diagnostico de accesibilidad",
            "supresión de barreras", "supresion de barreras", "barreras arquitectónicas", "barreras arquitectonicas"
        ],
    },
    "Smart City": {
        "keywords": [
            "smart city", "ciudad inteligente", "plan director smart city", "territorio inteligente",
            "transformación digital urbana", "transformacion digital urbana", "plataforma de ciudad",
            "gemelo digital urbano", "gemelo digital", "datos urbanos", "sensorización urbana", "sensorizacion urbana"
        ],
    },
    "Desarrollo local": {
        "keywords": [
            "desarrollo local", "estrategia de desarrollo local", "plan estratégico municipal",
            "plan estrategico municipal", "estrategia territorial", "desarrollo rural", "desarrollo urbano",
            "plan de dinamización", "plan de dinamizacion", "revitalización económica", "revitalizacion economica",
            "estrategia de revitalización", "estrategia de revitalizacion"
        ],
    },
}

# CPV orientados a consultoría/planificación. Se usan como señal adicional, no como criterio único.
CPV_PREFIXES = {"7141", "7124", "713112", "71313", "7941", "7322", "9071"}

# Verbos y expresiones que indican que el objeto es realmente planificación/consultoría.
PLANNING_INTENT_TERMS = [
    "elaboración", "elaboracion", "redacción", "redaccion", "asistencia técnica", "asistencia tecnica",
    "consultoría", "consultoria", "estudio", "diagnóstico", "diagnostico", "estrategia", "plan director",
    "plan municipal", "plan estratégico", "plan estrategico", "plan de acción", "plan de accion",
    "planeamiento", "ordenación", "ordenacion", "programa de actuación", "programa de actuacion",
    "documento estratégico", "documento estrategico", "diseño de estrategia", "diseno de estrategia"
]

# Términos que por sí solos suelen identificar un instrumento de planificación.
STRONG_PLAN_TERMS = [
    "agenda urbana", "pmus", "plan de movilidad urbana sostenible", "pgou", "plan general estructural",
    "pge", "pstd", "pdti", "destino turístico inteligente", "destino turistico inteligente",
    "paces", "paesc", "plan de accesibilidad", "estudio de paisaje", "plan territorial",
    "plan especial", "plan director smart city", "plan estratégico municipal", "plan estrategico municipal"
]

# Contratos que normalmente no son el tipo de servicio que se busca.
NEGATIVE_TITLE_TERMS = [
    "obras de", "obra de", "ejecución de obras", "ejecucion de obras", "suministro de", "suministro en",
    "mantenimiento de", "funcionamiento y mantenimiento", "servicio de mantenimiento", "alquiler de",
    "arrendamiento de", "producción audiovisual", "produccion audiovisual", "documentación gráfica",
    "documentacion grafica", "auditoría externa", "auditoria externa", "auditorías internas", "auditorias internas",
    "certificación", "certificacion", "limpieza de", "reparación de", "reparacion de", "renovación de la red",
    "renovacion de la red", "material necesario", "mobiliario", "iluminación", "iluminacion", "sonorización",
    "sonorizacion", "vallado", "pavimentación", "pavimentacion"
]

CV_TERMS = [
    "comunitat valenciana", "comunidad valenciana", "valència", "valencia", "alicante", "alacant",
    "castellón", "castellon", "castelló", "castello"
]

LOCAL_BODY_TERMS = [
    "ayuntamiento", "ajuntament", "diputación", "diputacio", "mancomunidad", "mancomunitat",
    "consorcio", "consorci", "entidad local", "entitat local"
]
