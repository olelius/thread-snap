import assert from 'node:assert/strict'
import test from 'node:test'
import { reputationMappingStatus, reputationMissingMappingIds, reputationPlatformVehicles, reputationValidationTargetIds } from '../src/features/reputation/reputation-validation.ts'

const vehicle = (id, mapping, enabled = true) => ({ id, enabled, mappings: mapping ? { autohome: mapping } : {}, series_name: '车系', vehicle_name: id, project_group: '项目组', role: 'focus', role_order: 1, removal_mode: 'delete' })
const mapping = (status = 'failed') => ({ platform_vehicle_id: '1', platform_url: 'https://k.autohome.com.cn/1/', platform_display_name: '车型', validation_status: status })

test('验证按钮只提交映射完整的待验证车型，未配置当前平台不计作缺失', () => {
  const vehicles = [vehicle('failed', mapping()), vehicle('pending', mapping('unverified')), vehicle('missing', null), vehicle('verified', mapping('verified')), vehicle('disabled', null, false)]
  assert.deepEqual(reputationValidationTargetIds(vehicles, 'autohome'), ['failed', 'pending'])
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'autohome'), [])
})

test('当前平台已有映射的空字段不会被加入验证目标，但会提示不完整', () => {
  const vehicles = [vehicle('incomplete', { ...mapping(), platform_url: '', validation_status: 'failed' }), vehicle('valid', mapping())]
  assert.deepEqual(reputationValidationTargetIds(vehicles, 'autohome'), ['valid'])
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'autohome'), ['incomplete'])
})

test('旧合同的已验证映射进入当前合同重新验证目标', () => {
  const legacy = { ...mapping('verified'), validation_contract_version: 'yiche-reputation-mapping-v1' }
  const legacyVehicle = vehicle('legacy', null)
  legacyVehicle.mappings = { yiche: legacy }
  const nativeVehicle = vehicle('native', null)
  nativeVehicle.mappings = { yiche: { ...legacy, validation_contract_version: 'yiche-native-app-mapping-v1' } }
  assert.deepEqual(reputationValidationTargetIds([legacyVehicle], 'yiche', 'yiche-reputation-mapping-v2'), ['legacy'])
  assert.deepEqual(reputationValidationTargetIds([nativeVehicle], 'yiche', 'yiche-reputation-mapping-v2'), [])
})

test('已验证项不参与待验证计数，仅当前平台的不完整映射单独报告', () => {
  const vehicles = [vehicle('verified', mapping('verified')), vehicle('failed', mapping()), vehicle('incomplete', { ...mapping(), platform_vehicle_id: '' }), vehicle('not-configured', null)]
  assert.equal(reputationValidationTargetIds(vehicles, 'autohome').length, 1)
  assert.equal(reputationMissingMappingIds(vehicles, 'autohome').length, 1)
})

test('切换平台后列表与启停统计只包含该平台记录，同名车型不自动合并', () => {
  const dcd = { ...vehicle('e5-dcd', null), vehicle_name: '银河E5', mappings: { dongchedi: mapping('verified') } }
  const yiche = { ...vehicle('e5-yiche', null), vehicle_name: '银河E5', mappings: { yiche: mapping('verified') } }
  const shared = { ...vehicle('shared', mapping('verified'), false), mappings: { autohome: mapping('verified'), yiche: mapping('verified') } }
  const vehicles = [dcd, yiche, shared, vehicle('unmapped', null)]
  const before = structuredClone(vehicles)
  assert.deepEqual(reputationPlatformVehicles(vehicles, 'yiche').map((v) => v.id), ['e5-yiche', 'shared'])
  assert.equal(reputationPlatformVehicles(vehicles, 'yiche').filter((v) => v.enabled).length, 1)
  assert.deepEqual(reputationPlatformVehicles(vehicles, 'dongchedi').map((v) => v.id), ['e5-dcd'])
  assert.deepEqual(reputationPlatformVehicles(vehicles, 'autohome').map((v) => v.id), ['shared'])
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'yiche'), [])
  assert.deepEqual(vehicles, before)
})

test('当前平台缺少任一字段或空映射均保留待修复，停用项不参与缺项计数', () => {
  const incomplete = ['platform_vehicle_id', 'platform_url', 'platform_display_name'].map((field) => vehicle(field, { ...mapping(), [field]: '  ' }))
  const vehicles = [...incomplete, vehicle('empty', {}), vehicle('disabled', {}, false), vehicle('other', null)]
  assert.equal(reputationPlatformVehicles(vehicles, 'autohome').length, 5)
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'autohome'), ['platform_vehicle_id', 'platform_url', 'platform_display_name', 'empty'])
  assert.deepEqual(reputationValidationTargetIds(vehicles, 'autohome'), [])
  assert.deepEqual(reputationPlatformVehicles(vehicles, 'yiche'), [])
})

test('当前验证状态覆盖缺映射、待验证、失败、有效与需重验五态', () => {
  assert.equal(reputationMappingStatus(undefined, 'autohome', 'v2'), 'missing')
  assert.equal(reputationMappingStatus(mapping('unverified'), 'autohome', 'v2'), 'unverified')
  assert.equal(reputationMappingStatus(mapping('failed'), 'autohome', 'v2'), 'failed')
  assert.equal(reputationMappingStatus({ ...mapping('verified'), validation_current: true }, 'autohome', 'v2'), 'verified')
  assert.equal(reputationMappingStatus({ ...mapping('verified'), validation_current: false, validation_contract_version: 'v2' }, 'autohome', 'v2'), 'stale')
  assert.equal(reputationMappingStatus({ ...mapping('verified'), platform_url: '', validation_current: true }, 'autohome', 'v2'), 'missing')
})

test('服务器有效性优先，缺少合同的旧验证进入重新验证而非持续显示通过', () => {
  const current = { ...mapping('verified'), validation_current: true, validation_contract_version: 'v3' }
  const stale = { ...mapping('verified'), validation_current: false, validation_contract_version: 'v2' }
  const noContract = mapping('verified')
  assert.equal(reputationMappingStatus(current, 'autohome', 'v2'), 'verified')
  assert.equal(reputationMappingStatus(noContract, 'autohome', 'v2'), 'stale')
  assert.deepEqual(reputationValidationTargetIds([vehicle('current', current), vehicle('stale', stale), vehicle('no-contract', noContract), vehicle('disabled', stale, false)], 'autohome', 'v2'), ['stale', 'no-contract'])
  assert.equal(stale.validation_status, 'verified')
})
