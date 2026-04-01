import { Resource } from './types';

export const mockResources: Resource[] = [
  { id: 'resource-01', title: 'Guia docente del curso', type: 'PDF', origin: 'interno', status: 'AVISO' },
  { id: 'resource-02', title: 'Planificacion semanal', type: 'Web', origin: 'interno', status: 'OK' },
  { id: 'resource-03', title: 'Video de bienvenida (YouTube)', type: 'Video', origin: 'externo', status: 'AVISO' },
  { id: 'resource-04', title: 'Notebook de practicas 1', type: 'Notebook', origin: 'interno', status: 'AVISO' },
  { id: 'resource-05', title: 'Infografia del temario', type: 'Other', origin: 'interno', status: 'ERROR' },
  { id: 'resource-06', title: 'Rubrica de evaluacion', type: 'PDF', origin: 'interno', status: 'OK' },
  { id: 'resource-07', title: 'Lectura complementaria OMS', type: 'Web', origin: 'externo', status: 'AVISO' },
  { id: 'resource-08', title: 'Seminario grabado', type: 'Video', origin: 'interno', status: 'ERROR' },
  { id: 'resource-09', title: 'Cuaderno de datos accesibles', type: 'Notebook', origin: 'interno', status: 'OK' },
  { id: 'resource-10', title: 'Banco de imagenes del tema 2', type: 'Other', origin: 'externo', status: 'AVISO' },
];
