export enum BedStatus {
  IDLE = 'idle',
  OCCUPIED = 'occupied',
  RESERVED = 'reserved',
  MAINTENANCE = 'maintenance',
}

export enum CareLevel {
  INDEPENDENT = 'independent',
  SEMI_DISABLED = 'semi_disabled',
  DISABLED = 'disabled',
  DEMENTIA = 'dementia',
}

export enum PaymentType {
  SELF = 'self',
  MEDICAL = 'medical',
  LONG_TERM_CARE = 'long_term_care',
}

export enum EmployeeRole {
  ADMIN = 'admin',
  NURSE = 'nurse',
  CAREGIVER = 'caregiver',
  FINANCE = 'finance',
  FAMILY = 'family',
}

export enum BillStatus {
  UNPAID = 'unpaid',
  PARTIAL = 'partial',
  PAID = 'paid',
  OVERDUE = 'overdue',
}

export enum ServiceOrderStatus {
  PENDING = 'pending',
  ASSIGNED = 'assigned',
  DONE = 'done',
  CANCELLED = 'cancelled',
}

export enum FeatureFlagKey {
  LONG_TERM_CARE = 'long_term_care',
  SECURITY_ALERTS = 'security_alerts',
  GPS_TRACKING = 'gps_tracking',
  OCR_LLM = 'ocr_llm',
  PAYMENT_GATEWAY = 'payment_gateway',
  MEDICATION = 'medication',
  INVENTORY = 'inventory',
  HR_SCHEDULING = 'hr_scheduling',
}

export const CARE_TASK_TEMPLATES: Record<CareLevel, string[]> = {
  [CareLevel.INDEPENDENT]: ['口腔护理', '协助洗漱'],
  [CareLevel.SEMI_DISABLED]: ['喂饭', '助浴', '如厕协助', '口腔护理'],
  [CareLevel.DISABLED]: ['喂饭', '翻身', '擦身', '如厕', '助浴', '口腔护理'],
  [CareLevel.DEMENTIA]: ['喂饭', '翻身', '擦身', '定向照护', '情绪安抚', '口腔护理'],
}

export const CARE_LEVEL_LABELS: Record<CareLevel, string> = {
  [CareLevel.INDEPENDENT]: '自理',
  [CareLevel.SEMI_DISABLED]: '半失能',
  [CareLevel.DISABLED]: '失能',
  [CareLevel.DEMENTIA]: '失智',
}

export const BED_STATUS_LABELS: Record<BedStatus, string> = {
  [BedStatus.IDLE]: '空闲',
  [BedStatus.OCCUPIED]: '入住',
  [BedStatus.RESERVED]: '预占',
  [BedStatus.MAINTENANCE]: '维修',
}
