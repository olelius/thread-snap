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
  cloud_concurrency: number
  cloud_concurrency_range: { min: number; max: number }
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

export type ReputationMetric = {
  raw?: string
  value?: string
  baseline_raw?: string
  baseline_value?: string
  delta?: string
  direction: 'up' | 'down' | 'same' | 'none'
  tone: 'positive' | 'negative' | 'neutral'
  comparison_status: string
}

export type ReputationEvidence = {
  id: string
  full_page_url: string
  metric_region_url: string
  full_page_sha256: string
  metric_region_sha256: string
}

export type ReputationResult = {
  id: string
  vehicle_id: string
  series_name: string
  vehicle_name: string
  role: 'focus' | 'competitor'
  role_position: number
  vehicle_position: number
  platform_code: string
  platform_name: string
  status: string
  metrics: Record<'score' | 'rank' | 'volume', ReputationMetric>
  evidence_required: boolean
  attempt_count?: number
  duration_ms?: number
  error_code?: string
  error_message?: string
  collected_at: string
  evidence?: ReputationEvidence
}

export type ReputationRun = {
  id: string
  number: string
  source_type: 'synthetic' | 'scheduled' | 'retry' | 'real_acceptance'
  scenario_id?: string
  run_type: 'baseline_initialization' | 'daily' | 'month_end'
  schedule_type?: 'daily' | 'month_end'
  planned_date: string
  root_run_id?: string
  parent_run_id?: string
  scope_version_id?: string
  planned_at?: string
  report_planned_at?: string | null
  report_generated_at?: string
  delayed: boolean
  concurrency?: number
  baseline_date?: string
  baseline_frozen_at?: string
  baseline_source_run_id?: string
  status: string
  platform_codes: string[]
  planned_count: number
  completed_count: number
  failed_count: number
  required_evidence_count: number
  complete_evidence_count: number
  report_status: string
  report_attempt_count?: number
  report_text?: string
  created_at: string
  started_at?: string
  finished_at?: string
  results?: ReputationResult[]
  downloads?: { txt?: string; xlsx?: string; evidence_zip?: string }
  retry_runs?: ReputationRun[]
  resolved_count?: number
  unresolved_count?: number
  linked_status?: string
}

export type ReputationSchedule = {
  timezone: string
  inspection_time: string
  report_time: string | null
  last_event?: {
    planned_date: string
    run_type: 'daily' | 'month_end'
    status: string
    message: string
    run_id?: string
    planned_at: string
  }
}

export type ReputationCapabilities = {
  reputation_synthetic_runs: boolean
  real_adapter_status: 'not_configured' | 'available'
  real_adapter_message: string
  scenarios: Array<{ id: string; name: string; description: string }>
}

export type ReputationScopeMapping = {
  platform_vehicle_id: string
  platform_url: string
  platform_display_name: string
  validation_status: 'unverified' | 'verified' | 'failed'
  validation_run_id?: string
  validation_attempt_id?: string
  validated_at?: string
  actual_name?: string
  latest_metrics?: { score?: string; rank?: string; volume?: string; rank_scope?: string }
  validation_error?: string
}

export type ReputationMappingValidation = {
  id: string
  platform_code: string
  status: string
  requested_count: number
  succeeded_count: number
  failed_count: number
  concurrency: number
  started_at: string
  finished_at?: string
  attempts: Array<{
    id: string
    vehicle_id: string
    attempt_number: number
    status: string
    actual_name?: string
    metrics: { score?: string; rank?: string; volume?: string; rank_scope?: string }
    error_code?: string
    error_message?: string
    duration_ms?: number
    full_page_url?: string
    metric_region_url?: string
  }>
  scope: ReputationScope
}

export type ReputationScopeVehicle = {
  id: string
  series_name: string
  vehicle_name: string
  project_group: string
  role: 'focus' | 'competitor'
  role_order: number
  enabled: boolean
  removal_mode: 'delete' | 'disable'
  mappings: Record<string, ReputationScopeMapping>
}

export type ReputationScope = {
  initialized: boolean
  revision: number
  vehicles: ReputationScopeVehicle[]
  published_version?: { id: string; version: number; published_at: string }
  source_sha256?: string
  updated_at?: string
  message?: string
  last_vehicle_action?: 'deleted' | 'disabled' | 'updated' | 'unchanged'
  last_vehicle_mapping_changed?: boolean
}

export type RunSourceOption = {
  key: string
  platform_code: string
  external_id: string
  circle_name: string
  source_name: string
  list_order: 'latest_reply' | 'latest_publish'
  list_order_name: string
}

export type PageResult<T> = { items: T[]; total: number; offset: number; limit: number; source_options?: RunSourceOption[] }

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
