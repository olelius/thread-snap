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
  rule_ids: string[]
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
  list_order: 'latest_reply' | 'latest_publish'
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
  source_names?: string[]
  list_orders?: Array<'latest_reply' | 'latest_publish'>
  list_order_names?: string[]
  planned_count: number
  completed_count: number
  failed_count: number
  waiting_reason?: string
  error_message?: string
  related_run_id?: string
  extraction_rule_id?: string
  extraction_rule_version?: number
  extraction_rules?: Array<{ id: string; name?: string; version: number }>
  summary_version: number
  created_at: string
  queued_at: string
  started_at?: string
  finished_at?: string
  tasks?: RunTask[]
  screenshot_summary?: { status: ScreenshotGroup['status']; group_count: number; ready_count: number; item_count?: number; negative_count?: number }
}

export type RunTask = {
  id: string
  platform_code: string
  circle_id?: string
  external_id: string
  circle_name?: string
  source_name?: string
  circle_url: string
  list_order: 'latest_reply' | 'latest_publish'
  list_order_name?: string
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
  source_name?: string
  list_order?: 'latest_reply' | 'latest_publish'
  list_order_name?: string
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
  analysis_status?: AnalysisStatus
  sentiment_result?: SentimentResult
  sentiment_source?: SentimentSource
  sentiment_updated_at?: string
  sentiment?: SentimentDetail
  comments: Array<{
    platform_comment_id?: string
    author?: string
    content?: string
    published_at?: string
    like_count?: number
  }>
}

export type SentimentResult = 'negative' | 'non_negative' | 'unrelated'
export type SentimentSource = 'ai' | 'manual' | 'inherited_manual'
export type AnalysisStatus = 'analysis_queued' | 'analysis_running' | 'analysis_completed' | 'analysis_partial' | 'analysis_failed' | 'analysis_paused' | 'analysis_disabled'

export type SentimentConfig = {
  revision: number
  enabled: boolean
  api_base_url: string
  api_key_configured: boolean
  model_code: string
  model_name: string
  model_provider: 'hosted' | 'local'
  model_input_mode: 'multimodal' | 'text_only'
  available_models: string[]
  model_connections: Record<string, { api_base_url: string; api_key_configured: boolean }>
  validation_status: 'unverified' | 'valid' | 'invalid'
  validation_error?: string
  validated_at?: string
  subject: { brand: string; products: string[]; supplement?: string; version: number }
}

export type SentimentDetail = {
  analysis_status?: AnalysisStatus
  result?: SentimentResult
  source?: SentimentSource
  summary?: string
  matched_subjects: string[]
  primary_category?: string
  secondary_categories: string[]
  modalities?: {
    text: { status: string; evidence: string[] }
    image: SentimentMediaCoverage
    video_visual: SentimentMediaCoverage
    video_audio: SentimentMediaCoverage
  }
  model_code?: string
  provider_request_id?: string
  duration_ms?: number
  error_code?: string
  error_message?: string
  updated_at?: string
  can_manual_correct: boolean
  can_restore_ai: boolean
  manual_history: Array<{ id: string; action: string; result?: SentimentResult; primary_category?: string; secondary_categories: string[]; note?: string; inherited: boolean; created_at: string }>
}

export type SentimentMediaCoverage = { status: string; expected_count: number; processed_count: number; items: Array<{ input_index: number; url_hash: string; status: string; evidence: string[] }> }

export type PageResult<T> = { items: T[]; total: number; offset: number; limit: number }

export type PostNavigation = {
  previous_id?: string
  next_id?: string
  position: number
  total: number
}

export type ScreenshotTile = {
  index: number
  sha256: string
  width: number
  height: number
  image_url: string
}

export type ScreenshotArtifact = {
  version: number
  created_at: string
  package_sha256: string
  download_url: string
  tiles: ScreenshotTile[]
  items: Array<{ post_id: string; platform_post_id: string; title?: string; sentiment_result: SentimentResult; run_number: string; captured_at: string; tile_index: number; y: number; height: number }>
}

export type ScreenshotGroup = {
  id?: string
  circle_name?: string
  external_id: string
  section: string
  list_order: 'latest_reply' | 'latest_publish'
  status: 'evidence_pending' | 'evidence_running' | 'waiting_for_sentiment' | 'rendering' | 'ready' | 'empty' | 'failed' | 'not_collected' | 'not_applicable'
  current_version: number
  item_count: number
  negative_count: number
  error_message?: string
  evidence: Array<{ id: string; page_number: number; exact_url: string; captured_at: string; sha256: string; adapter_version: string; browser_version: string; device_scale_factor: number; width: number; height: number; image_url: string; download_url: string }>
  artifact?: ScreenshotArtifact
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
  fresh_profile: boolean
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
