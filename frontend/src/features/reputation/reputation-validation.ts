import type { ReputationScopeVehicle } from '@/lib/types'

/** 返回当前平台有完整映射且尚未验证的启用车型。 */
export function reputationValidationTargetIds(vehicles: ReputationScopeVehicle[], platformCode: string): string[] {
  return vehicles
    .filter((vehicle) => {
      if (!vehicle.enabled) return false
      const mapping = vehicle.mappings[platformCode]
      return Boolean(mapping && mapping.validation_status !== 'verified' && mapping.platform_vehicle_id.trim() && mapping.platform_url.trim() && mapping.platform_display_name.trim())
    })
    .map((vehicle) => vehicle.id)
}

/** 返回当前平台缺少必要映射字段的启用车型。 */
export function reputationMissingMappingIds(vehicles: ReputationScopeVehicle[], platformCode: string): string[] {
  return vehicles
    .filter((vehicle) => {
      if (!vehicle.enabled) return false
      const mapping = vehicle.mappings[platformCode]
      return !mapping || !mapping.platform_vehicle_id.trim() || !mapping.platform_url.trim() || !mapping.platform_display_name.trim()
    })
    .map((vehicle) => vehicle.id)
}
