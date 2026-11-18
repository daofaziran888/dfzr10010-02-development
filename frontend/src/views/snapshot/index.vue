<template>
  <section class="page" data-module="snapshot">
    <header class="page-head">
      <div>
        <h2>表快照管理</h2>
        <p class="page-desc">维护表快照的版本管理、保留策略与创建方式，为表快照管理提供可验证的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记快照记录</button>
        <button class="btn" type="button" @click="exportRows">导出表快照管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="panel">
      <header class="panel-head">
        <h3>保留策略</h3>
        <span class="panel-meta">当前版本 {{ policy.策略版本 || '—' }} · 确认于 {{ policy.确认时间 || '—' }}</span>
      </header>
      <div class="panel-body policy-grid">
        <label class="filter-item">
          <span>保留档位</span>
          <select v-model="policyForm.保留档位">
            <option v-for="tier in tiers" :key="tier" :value="tier">{{ tier }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>保留边界</span>
          <select v-model="policyForm.保留边界">
            <option v-for="boundary in boundaries" :key="boundary" :value="boundary">{{ boundary }}</option>
          </select>
        </label>
        <button class="btn primary" type="button" @click="confirmPolicy">确认保留策略</button>
        <span class="panel-meta">覆盖创建方式：{{ coveredMethods }}</span>
      </div>
      <p v-if="policyMessage" class="panel-note">{{ policyMessage }}</p>
    </section>

    <section class="panel">
      <header class="panel-head">
        <h3>数据表快照清理结果</h3>
        <div class="panel-actions">
          <span class="panel-meta">
            策略版本 {{ cleanup.策略版本 || '—' }} · {{ cleanup.生成时间 || '—' }} 生成 ·
            候选 {{ cleanup.候选总数 ?? 0 }} · 保留 {{ cleanup.保留数 ?? 0 }} · 删除 {{ cleanup.删除数 ?? 0 }}
          </span>
          <button class="btn" type="button" @click="refreshCleanup">重新计算清理结果</button>
        </div>
      </header>
      <div class="panel-body cleanup-filter">
        <label v-for="option in cleanupFilters" :key="option" class="filter-check">
          <input v-model="cleanupFilter" type="radio" name="cleanup-filter" :value="option" />
          <span>{{ option }}</span>
        </label>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in cleanupColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredCleanup" :key="String(row.快照编号)" :class="{ 'row-delete': row.决策 === '删除' }">
            <td v-for="column in cleanupColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!filteredCleanup.length">
            <td :colspan="cleanupColumns.length" class="empty-state">暂无清理结果，请先确认保留策略</td>
          </tr>
        </tbody>
      </table>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无表快照管理数据，可先登记快照记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条表快照管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

interface Policy {
  策略版本?: string
  保留档位?: string
  保留天数?: number
  保留边界?: string
  适用创建方式?: string[]
  确认时间?: string
}

interface CleanupResult {
  策略版本?: string
  保留档位?: string
  保留边界?: string
  生成时间?: string
  候选总数?: number
  保留数?: number
  删除数?: number
  候选明细: Row[]
}

const ENDPOINT = '/api/snapshot'
const columns = ["快照编号", "表名称", "快照时间", "最近访问时间", "快照版本", "快照大小", "保留天数", "创建方式", "快照状态"]
const actions = ["创建快照", "恢复快照", "清理快照"]
const stats = [{"label": "快照记录总数", "value": 0}, {"label": "保留中快照", "value": 0}, {"label": "已清理快照", "value": 0}]
const tiers = ["7天", "14天", "30天"]
const boundaries = ["按创建时间", "按最近访问时间"]
const cleanupColumns = ["快照编号", "表名称", "创建方式", "快照时间", "最近访问时间", "决策", "依据", "核对结论"]
const cleanupFilters = ["全部", "保留", "删除"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const policy = ref<Policy>({})
const policyForm = ref({ 保留档位: '7天', 保留边界: '按创建时间' })
const policyMessage = ref('')
const cleanup = ref<CleanupResult>({ 候选明细: [] })
const cleanupFilter = ref('全部')

const coveredMethods = computed(() => {
  const methods = policy.value.适用创建方式
  return Array.isArray(methods) && methods.length ? methods.join('、') : '—'
})

const filteredCleanup = computed<Row[]>(() => {
  const items = cleanup.value.候选明细 ?? []
  if (cleanupFilter.value === '全部') {
    return items
  }
  return items.filter((item) => item.决策 === cleanupFilter.value)
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '快照记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('表快照管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '表快照管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('快照记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '表快照管理列表读取失败'
  }
}

async function loadPolicy() {
  try {
    const response = await request(`${ENDPOINT}/policy`)
    if (!response.ok) {
      throw new Error('保留策略读取失败')
    }
    policy.value = await response.json()
    policyForm.value = {
      保留档位: String(policy.value.保留档位 ?? '7天'),
      保留边界: String(policy.value.保留边界 ?? '按创建时间'),
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保留策略读取失败'
  }
}

async function loadCleanup() {
  try {
    const response = await request(`${ENDPOINT}/cleanup-result`)
    if (!response.ok) {
      throw new Error('清理结果读取失败')
    }
    cleanup.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清理结果读取失败'
  }
}

async function confirmPolicy() {
  errorMessage.value = ''
  policyMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/policy`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...policyForm.value } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '保留策略确认失败')
    }
    policy.value = payload.entry ?? policy.value
    policyMessage.value = payload.message || '保留策略已确认'
    await loadCleanup()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保留策略确认失败'
  }
}

async function refreshCleanup() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/cleanup-result/refresh`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    if (!response.ok) {
      throw new Error('清理结果重新计算失败')
    }
    cleanup.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '清理结果重新计算失败'
  }
}

onMounted(async () => {
  await Promise.all([loadPolicy(), loadCleanup(), reload()])
})
</script>
