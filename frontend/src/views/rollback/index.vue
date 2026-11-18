<template>
  <section class="page" data-module="rollback">
    <header class="page-head">
      <div>
        <h2>数据回滚恢复</h2>
        <p class="page-desc">维护数据回滚的版本追踪、影响评估与恢复计时，为数据回滚恢复提供可审计的数据工程流程。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记回滚记录</button>
        <button class="btn" type="button" @click="exportRows">导出数据回滚恢复清单</button>
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
        <h3>回滚工作台待办</h3>
        <span class="panel-meta">与数据表快照清理结果同源 · 共 {{ todos.length }} 条 · 待核对 {{ pendingCount }} 条</span>
      </header>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in todoColumns" :key="column">{{ column }}</th>
            <th>核对操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="todo in todos" :key="String(todo.待办编号)">
            <td v-for="column in todoColumns" :key="column">{{ todo[column] ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="verifyTodo(todo, '核对一致')">核对一致</button>
              <button class="link" type="button" @click="verifyTodo(todo, '核对不一致')">核对不一致</button>
            </td>
          </tr>
          <tr v-if="!todos.length">
            <td :colspan="todoColumns.length + 1" class="empty-state">暂无回滚工作台待办，请先在快照页确认保留策略</td>
          </tr>
        </tbody>
      </table>
      <p v-if="todoMessage" class="panel-note">{{ todoMessage }}</p>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无数据回滚恢复数据，可先登记回滚记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据回滚恢复记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/rollback'
const columns = ["记录编号", "表名称", "回滚版本", "回滚原因", "影响范围", "恢复耗时", "回滚时间", "回滚状态"]
const actions = ["执行回滚", "确认恢复", "归档记录"]
const stats = [{"label": "回滚记录总数", "value": 0}, {"label": "回滚中记录", "value": 0}, {"label": "已回滚记录", "value": 0}]
const todoColumns = ["待办编号", "快照编号", "表名称", "决策", "依据", "核对结论", "来源"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const todos = ref<Row[]>([])
const todoMessage = ref('')

const pendingCount = computed(() => todos.value.filter((todo) => todo.核对结论 === '待核对').length)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '回滚记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('数据回滚恢复动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回滚恢复操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('回滚记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据回滚恢复列表读取失败'
  }
}

async function loadTodos() {
  try {
    const response = await request(`${ENDPOINT}/workbench`)
    if (!response.ok) {
      throw new Error('回滚工作台待办读取失败')
    }
    const payload = await response.json()
    todos.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回滚工作台待办读取失败'
  }
}

async function verifyTodo(todo: Row, conclusion: string) {
  errorMessage.value = ''
  todoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/workbench/${todo.id}/verify`, {
      method: 'POST',
      body: JSON.stringify({ values: { 核对结论: conclusion } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '待办核对失败')
    }
    todoMessage.value = payload.message || '待办已核对'
    await loadTodos()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待办核对失败'
  }
}

onMounted(async () => {
  await Promise.all([loadTodos(), reload()])
})
</script>
