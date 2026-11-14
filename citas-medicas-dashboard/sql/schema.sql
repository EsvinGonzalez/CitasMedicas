-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.sucursal (
  id integer NOT NULL DEFAULT nextval('sucursal_id_seq'::regclass),
  nombre character varying NOT NULL,
  direccion text,
  activa boolean DEFAULT true,
  CONSTRAINT sucursal_pkey PRIMARY KEY (id)
);
CREATE TABLE public.telefono_sucursal (
  id integer NOT NULL DEFAULT nextval('telefono_sucursal_id_seq'::regclass),
  sucursal_id integer,
  numero character varying NOT NULL,
  tipo character varying,
  principal boolean DEFAULT false,
  CONSTRAINT telefono_sucursal_pkey PRIMARY KEY (id),
  CONSTRAINT telefono_sucursal_sucursal_id_fkey FOREIGN KEY (sucursal_id) REFERENCES public.sucursal(id)
);
CREATE TABLE public.especialidad (
  id integer NOT NULL DEFAULT nextval('especialidad_id_seq'::regclass),
  nombre character varying NOT NULL UNIQUE,
  color character varying DEFAULT '#3B82F6'::character varying,
  duracion_min integer DEFAULT 30,
  tarifa_base numeric NOT NULL,
  CONSTRAINT especialidad_pkey PRIMARY KEY (id)
);
CREATE TABLE public.diagnostico (
  id integer NOT NULL DEFAULT nextval('diagnostico_id_seq'::regclass),
  codigo character varying NOT NULL UNIQUE,
  nombre character varying NOT NULL,
  descripcion text,
  CONSTRAINT diagnostico_pkey PRIMARY KEY (id)
);
CREATE TABLE public.cita (
  id integer NOT NULL DEFAULT nextval('cita_id_seq'::regclass),
  sucursal_id integer,
  especialidad_id integer,
  medico_id integer,
  paciente_id integer,
  fecha date NOT NULL,
  hora time without time zone NOT NULL,
  estado character varying DEFAULT 'pendiente'::character varying,
  motivo text,
  creado_en timestamp without time zone DEFAULT now(),
  CONSTRAINT cita_pkey PRIMARY KEY (id),
  CONSTRAINT cita_sucursal_id_fkey FOREIGN KEY (sucursal_id) REFERENCES public.sucursal(id),
  CONSTRAINT cita_especialidad_id_fkey FOREIGN KEY (especialidad_id) REFERENCES public.especialidad(id),
  CONSTRAINT fk_cita_medico FOREIGN KEY (medico_id) REFERENCES public.medico(id),
  CONSTRAINT fk_cita_paciente FOREIGN KEY (paciente_id) REFERENCES public.paciente(id)
);
CREATE TABLE public.detalle_cita (
  id integer NOT NULL DEFAULT nextval('detalle_cita_id_seq'::regclass),
  cita_id integer,
  concepto character varying NOT NULL,
  cantidad integer DEFAULT 1,
  notas text,
  CONSTRAINT detalle_cita_pkey PRIMARY KEY (id),
  CONSTRAINT detalle_cita_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);
CREATE TABLE public.detalle_diagnostico (
  id integer NOT NULL DEFAULT nextval('detalle_diagnostico_id_seq'::regclass),
  cita_id integer,
  diagnostico_id integer,
  es_principal boolean DEFAULT false,
  observaciones text,
  CONSTRAINT detalle_diagnostico_pkey PRIMARY KEY (id),
  CONSTRAINT detalle_diagnostico_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id),
  CONSTRAINT detalle_diagnostico_diagnostico_id_fkey FOREIGN KEY (diagnostico_id) REFERENCES public.diagnostico(id)
);
CREATE TABLE public.auditoria_cita (
  id integer NOT NULL DEFAULT nextval('auditoria_cita_id_seq'::regclass),
  cita_id integer,
  accion character varying NOT NULL,
  estado_anterior character varying,
  estado_nuevo character varying,
  usuario_id integer,
  fecha timestamp without time zone DEFAULT now(),
  CONSTRAINT auditoria_cita_pkey PRIMARY KEY (id),
  CONSTRAINT auditoria_cita_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);
CREATE TABLE public.persona (
  id integer NOT NULL DEFAULT nextval('persona_id_seq'::regclass),
  nombre character varying NOT NULL,
  tipo_documento character varying DEFAULT 'DNI'::character varying,
  numero_documento character varying NOT NULL UNIQUE,
  fecha_nacimiento date,
  fecha_registro date DEFAULT CURRENT_DATE,
  CONSTRAINT persona_pkey PRIMARY KEY (id)
);
CREATE TABLE public.telefono_persona (
  id integer NOT NULL DEFAULT nextval('telefono_persona_id_seq'::regclass),
  persona_id integer,
  numero character varying NOT NULL,
  tipo character varying,
  principal boolean DEFAULT false,
  CONSTRAINT telefono_persona_pkey PRIMARY KEY (id),
  CONSTRAINT telefono_persona_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES public.persona(id)
);
CREATE TABLE public.rol (
  id integer NOT NULL DEFAULT nextval('rol_id_seq'::regclass),
  nombre character varying NOT NULL UNIQUE,
  CONSTRAINT rol_pkey PRIMARY KEY (id)
);
CREATE TABLE public.permiso (
  id integer NOT NULL DEFAULT nextval('permiso_id_seq'::regclass),
  rol_id integer,
  modulo character varying NOT NULL,
  accion character varying NOT NULL,
  CONSTRAINT permiso_pkey PRIMARY KEY (id),
  CONSTRAINT permiso_rol_id_fkey FOREIGN KEY (rol_id) REFERENCES public.rol(id)
);
CREATE TABLE public.usuario (
  id integer NOT NULL DEFAULT nextval('usuario_id_seq'::regclass),
  persona_id integer,
  email character varying NOT NULL UNIQUE,
  password_hash character varying NOT NULL,
  secreto_2fa character varying,
  dos_fa_activo boolean DEFAULT false,
  activo boolean DEFAULT true,
  rol_id integer,
  CONSTRAINT usuario_pkey PRIMARY KEY (id),
  CONSTRAINT usuario_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES public.persona(id),
  CONSTRAINT usuario_rol_id_fkey FOREIGN KEY (rol_id) REFERENCES public.rol(id)
);
CREATE TABLE public.paciente (
  id integer NOT NULL DEFAULT nextval('paciente_id_seq'::regclass),
  persona_id integer,
  usuario_id integer,
  tipo_sangre character varying,
  alergias text,
  CONSTRAINT paciente_pkey PRIMARY KEY (id),
  CONSTRAINT paciente_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES public.persona(id),
  CONSTRAINT paciente_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuario(id)
);
CREATE TABLE public.medico (
  id integer NOT NULL DEFAULT nextval('medico_id_seq'::regclass),
  persona_id integer,
  usuario_id integer,
  cedula character varying NOT NULL UNIQUE,
  activo boolean DEFAULT true,
  CONSTRAINT medico_pkey PRIMARY KEY (id),
  CONSTRAINT medico_persona_id_fkey FOREIGN KEY (persona_id) REFERENCES public.persona(id),
  CONSTRAINT medico_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuario(id)
);
CREATE TABLE public.videoconsulta (
  id integer NOT NULL DEFAULT nextval('videoconsulta_id_seq'::regclass),
  cita_id integer UNIQUE,
  url_sala character varying NOT NULL,
  estado character varying DEFAULT 'programada'::character varying,
  consentimiento_grabacion boolean DEFAULT false,
  grabacion_url text,
  iniciada_en timestamp without time zone,
  finalizada_en timestamp without time zone,
  CONSTRAINT videoconsulta_pkey PRIMARY KEY (id),
  CONSTRAINT videoconsulta_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);
CREATE TABLE public.receta_electronica (
  id integer NOT NULL DEFAULT nextval('receta_electronica_id_seq'::regclass),
  cita_id integer,
  medico_id integer,
  paciente_id integer,
  fecha_emision date DEFAULT CURRENT_DATE,
  firma_digital text,
  pdf_url text,
  CONSTRAINT receta_electronica_pkey PRIMARY KEY (id),
  CONSTRAINT receta_electronica_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id),
  CONSTRAINT receta_electronica_medico_id_fkey FOREIGN KEY (medico_id) REFERENCES public.medico(id),
  CONSTRAINT receta_electronica_paciente_id_fkey FOREIGN KEY (paciente_id) REFERENCES public.paciente(id)
);
CREATE TABLE public.item_receta (
  id integer NOT NULL DEFAULT nextval('item_receta_id_seq'::regclass),
  receta_id integer,
  medicamento character varying NOT NULL,
  dosis character varying NOT NULL,
  frecuencia character varying NOT NULL,
  duracion_dias integer NOT NULL,
  CONSTRAINT item_receta_pkey PRIMARY KEY (id),
  CONSTRAINT item_receta_receta_id_fkey FOREIGN KEY (receta_id) REFERENCES public.receta_electronica(id)
);
CREATE TABLE public.factura (
  id integer NOT NULL DEFAULT nextval('factura_id_seq'::regclass),
  cita_id integer UNIQUE,
  fecha_emision date DEFAULT CURRENT_DATE,
  metodo_pago character varying,
  estado character varying DEFAULT 'pendiente'::character varying,
  total numeric DEFAULT 0,
  CONSTRAINT factura_pkey PRIMARY KEY (id),
  CONSTRAINT factura_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);
CREATE TABLE public.detalle_factura (
  id integer NOT NULL DEFAULT nextval('detalle_factura_id_seq'::regclass),
  factura_id integer,
  concepto character varying NOT NULL,
  cantidad integer DEFAULT 1,
  precio_unitario numeric NOT NULL,
  subtotal numeric DEFAULT ((cantidad)::numeric * precio_unitario),
  CONSTRAINT detalle_factura_pkey PRIMARY KEY (id),
  CONSTRAINT detalle_factura_factura_id_fkey FOREIGN KEY (factura_id) REFERENCES public.factura(id)
);
CREATE TABLE public.pago (
  id integer NOT NULL DEFAULT nextval('pago_id_seq'::regclass),
  factura_id integer,
  monto numeric NOT NULL,
  pasarela character varying,
  estado_transaccion character varying DEFAULT 'pendiente'::character varying,
  referencia_externa character varying,
  CONSTRAINT pago_pkey PRIMARY KEY (id),
  CONSTRAINT pago_factura_id_fkey FOREIGN KEY (factura_id) REFERENCES public.factura(id)
);
CREATE TABLE public.notificacion (
  id integer NOT NULL DEFAULT nextval('notificacion_id_seq'::regclass),
  usuario_id integer,
  cita_id integer,
  tipo character varying NOT NULL,
  canal character varying NOT NULL,
  estado character varying DEFAULT 'pendiente'::character varying,
  programada_para timestamp without time zone,
  enviada_en timestamp without time zone,
  CONSTRAINT notificacion_pkey PRIMARY KEY (id),
  CONSTRAINT notificacion_usuario_id_fkey FOREIGN KEY (usuario_id) REFERENCES public.usuario(id),
  CONSTRAINT notificacion_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);
CREATE TABLE public.prediccion_inasistencia (
  id integer NOT NULL DEFAULT nextval('prediccion_inasistencia_id_seq'::regclass),
  cita_id integer UNIQUE,
  probabilidad double precision NOT NULL,
  modelo_usado character varying,
  generada_en timestamp without time zone DEFAULT now(),
  CONSTRAINT prediccion_inasistencia_pkey PRIMARY KEY (id),
  CONSTRAINT prediccion_inasistencia_cita_id_fkey FOREIGN KEY (cita_id) REFERENCES public.cita(id)
);