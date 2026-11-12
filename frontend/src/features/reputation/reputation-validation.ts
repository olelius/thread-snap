import type { ReputationScopeMapping, ReputationScopeVehicle } from '@/lib/types'

/** 只保留已建立当前平台映射的车型；字段不完整的映射仍保留，便于修复。 */
export function reputationPlatformVehicles(vehicles: ReputationScopeVehicle[], platformCode: string): ReputationScopeVehicle[] {
  return vehicles.filter((vehicle) => Boolean(vehicle.mappings[platformCode]))
}

/** 映射表、统计和验证按钮共享的展示状态；不会修改存储的验证记录。 */
export function reputationMappingStatus(mapping: ReputationScopeMapping | undefined, platformCode: string, currentContractVersion?: string): 'missing' | 'unverified' | 'verified' | 'failed' | 'stale' {
  if (!mapping?.platform_vehicle_id?.trim() || !mapping.platform_url?.trim() || !mapping.platform_display_name?.trim()) return 'missing'
  if (mapping.validation_status !== 'verified') return mapping.validation_status === 'failed' ? 'failed' : 'unverified'
  // 后端已同时核对哈希与合同；显式 false 不回退到旧的 verified 标签。
  if (typeof mapping.validation_current === 'boolean') return mapping.validation_current ? 'verified' : 'stale'
  const compatibleLegacy = platformCode === 'yiche' && mapping.validation_contract_version === 'yiche-native-app-mapping-v1'
  if (currentContractVersion && mapping.validation_contract_version !== currentContractVersion && !compatibleLegacy) return 'stale'
  return 'verified'
}

/** 返回当前平台有完整映射且尚未验证的启用车型。 */
export function reputationValidationTargetIds(vehicles: ReputationScopeVehicle[], platformCode: string, currentContractVersion?: string): string[] {
  return vehicles
    .filter((vehicle) => {
      if (!vehicle.enabled) return false
      const state = reputationMappingStatus(vehicle.mappings[platformCode], platformCode, currentContractVersion)
      return state !== 'missing' && state !== 'verified'
    })
    .map((vehicle) => vehicle.id)
}

/** 返回当前平台已有映射但缺少必要字段的启用车型，不统计其他平台专属记录。 */
export function reputationMissingMappingIds(vehicles: ReputationScopeVehicle[], platformCode: string): string[] {
  return reputationPlatformVehicles(vehicles, platformCode)
    .filter((vehicle) => {
      if (!vehicle.enabled) return false
      return reputationMappingStatus(vehicle.mappings[platformCode], platformCode) === 'missing'
    })
    .map((vehicle) => vehicle.id)
}
