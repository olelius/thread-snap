import assert from 'node:assert/strict'
import test from 'node:test'
import { reputationMissingMappingIds, reputationValidationTargetIds } from '../src/features/reputation/reputation-validation.ts'

const vehicle = (id, mapping, enabled = true) => ({ id, enabled, mappings: mapping ? { autohome: mapping } : {}, series_name: '车系', vehicle_name: id, project_group: '项目组', role: 'focus', role_order: 1, removal_mode: 'delete' })
const mapping = (status = 'failed') => ({ platform_vehicle_id: '1', platform_url: 'https://k.autohome.com.cn/1/', platform_display_name: '车型', validation_status: status })

test('验证按钮只提交映射完整的待验证车型，并跳过缺失映射', () => {
  const vehicles = [vehicle('failed', mapping()), vehicle('pending', mapping('unverified')), vehicle('missing', null), vehicle('verified', mapping('verified')), vehicle('disabled', null, false)]
  assert.deepEqual(reputationValidationTargetIds(vehicles, 'autohome'), ['failed', 'pending'])
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'autohome'), ['missing'])
})

test('其他平台或空字段不会被错误加入汽车之家验证目标', () => {
  const vehicles = [vehicle('other-platform', { ...mapping(), platform_url: '', validation_status: 'failed' }), vehicle('valid', mapping())]
  assert.deepEqual(reputationValidationTargetIds(vehicles, 'autohome'), ['valid'])
  assert.deepEqual(reputationMissingMappingIds(vehicles, 'autohome'), ['other-platform'])
})

test('已验证项不参与待验证计数，缺失映射单独报告', () => {
  const vehicles = [vehicle('verified', mapping('verified')), vehicle('failed', mapping()), vehicle('missing', null)]
  assert.equal(reputationValidationTargetIds(vehicles, 'autohome').length, 1)
  assert.equal(reputationMissingMappingIds(vehicles, 'autohome').length, 1)
})
