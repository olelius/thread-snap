export type Platform = {
  code: string
  display_name: string
  adapter_status: 'available' | 'not_integrated'
  enabled: boolean
  internal_concurrency: number
  quantity_range: { min: number; max: number }
  concurrency_range: { min: number; max: number }
  adapter_version?: string
  notes?: string[]
}

export type ExtractionRule = {
  id: string
  name: string
  version: number
  platform_quantities: Record<string, number>
  circle_ids: string[]
  archived: boolean
  updated_at: string
}

export type ScheduleNode = {
  id: string
  weekdays: number[]
  time: string
  enabled: boolean
  rule_id: string
  updated_at: string
}

export type ExtractionPlan = {
  timezone: string
  revision: number
  rules: ExtractionRule[]
  archived_rules: ExtractionRule[]
  nodes: ScheduleNode[]
}

export type Circle = {
  id: string
  platform_code: string
  external_id: string
  name?: string
  url: string
  vehicle_id?: string
  vehicle_name?: string
  auto_enabled: boolean
  section: string
  validation_status: string
  validation_error?: string
  first_validated_at?: string
  validated_at?: string
}

export type Vehicle = { id: string; name: string; circles: Circle[] }

export type Run = {
  id: string
  number: string
  trigger_type: 'manual' | 'scheduled'
  trigger_type_name: string
  input_mode: 'circle_discovery' | 'url_list'
  status: string
  status_name: string
  queue_position?: number
  platform_count: number
  platform_codes?: string[]
  circle_count: number
  circle_names?: string[]
  planned_count: number
  completed_count: number
  failed_count: number
  waiting_reason?: string
  error_message?: string
  related_run_id?: string
  extraction_rule_id?: string
  extraction_rule_version?: number
  summary_version: number
  created_at: string
  queued_at: string
  started_at?: string
  finished_at?: string
  tasks?: RunTask[]
}

export type RunTask = {
  id: string
  platform_code: string
  circle_id?: string
  external_id: string
  circle_name?: string
  circle_url: string
  status: string
  status_name: string
  target_count: number
  completed_count: number
  failed_count: number
  error_code?: string
  error_message?: string
  stop_reason?: string
  created_at?: string
  started_at?: string
  finished_at?: string
}

export type Post = {
  id: string
  platform_code?: string
  circle_id?: string
  circle_name?: string
  platform_post_id: string
  url: string
  title?: string
  author?: string
  published_at?: string
  content?: string
  image_urls: string[]
  video_urls: string[]
  reply_count?: number
  like_count?: number
  section?: string
  visibility: 'visible' | 'hidden' | 'unknown'
  raw_status?: unknown
  comments: Array<{
    platform_comment_id?: string
    author?: string
    content?: string
    published_at?: string
    like_count?: number
  }>
}

export type PageResult<T> = { items: T[]; total: number; offset: number; limit: number }

export type PostNavigation = {
  previous_id?: string
  next_id?: string
  position: number
  total: number
}

export type SessionStatus = {
  platform_code: string
  status: string
  status_name?: string
  last_verified_at?: string
  error_message?: string
}

export type AuthTask = {
  id: string
  platform_code: string
  status: string
  status_name: string
  page_status: string
  expires_at: string
  error_code?: string
  error_message?: string
  http_status?: number
  ticket?: string
  websocket_path: string
}

export type Template = {
  id: string
  name: string
  versions: Array<{
    template_id: string
    template_name: string
    version_id: string
    version: number
    created_at: string
  }>
}

export type ApiErrorPayload = {
  code: string
  message: string
  details?: Array<Record<string, unknown>>
  request_id?: string
}
