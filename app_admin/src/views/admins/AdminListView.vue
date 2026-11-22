<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'

import {
  createAdmin,
  createRole,
  deleteRole,
  listAdmins,
  listRoles,
  updateAdmin,
  updateRole,
} from '@/api/admin'
import type { AdminItem, AdminRoleItem, PermissionItem } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const activeTab = ref<'admins' | 'roles'>('admins')
const loading = ref(false)
const saving = ref(false)
const admins = ref<AdminItem[]>([])
const roles = ref<AdminRoleItem[]>([])
const permissions = ref<PermissionItem[]>([])
const keyword = ref('')
const statusFilter = ref('')

const adminDialogVisible = ref(false)
const editingAdmin = ref<AdminItem | null>(null)
const adminForm = reactive({
  username: '',
  password: '',
  displayName: '',
  status: 'active' as 'active' | 'disabled',
  roleIds: [] as string[],
})

const roleDialogVisible = ref(false)
const editingRole = ref<AdminRoleItem | null>(null)
const roleForm = reactive({
  code: '',
  name: '',
  permissions: [] as string[],
})

const permissionLabel = computed(() => {
  const map: Record<string, string> = {}
  for (const item of permissions.value) map[item.code] = item.label
  return map
})

async function loadAll() {
  loading.value = true
  try {
    const [adminData, roleData] = await Promise.all([
      listAdmins({
        keyword: keyword.value || undefined,
        status: statusFilter.value || undefined,
      }),
      listRoles(),
    ])
    admins.value = adminData.items
    roles.value = roleData.items
    permissions.value = roleData.permissions
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreateAdmin() {
  editingAdmin.value = null
  Object.assign(adminForm, {
    username: '',
    password: '',
    displayName: '',
    status: 'active',
    roleIds: [],
  })
  adminDialogVisible.value = true
}

function openEditAdmin(admin: AdminItem) {
  editingAdmin.value = admin
  Object.assign(adminForm, {
    username: admin.username,
    password: '',
    displayName: admin.displayName,
    status: admin.status === 'disabled' ? 'disabled' : 'active',
    roleIds: admin.roles.map((role) => role.id),
  })
  adminDialogVisible.value = true
}

async function saveAdmin() {
  if (!adminForm.displayName.trim()) {
    ElMessage.warning('请输入显示名称')
    return
  }
  if (!adminForm.roleIds.length) {
    ElMessage.warning('至少选择一个角色')
    return
  }
  if (adminForm.password && adminForm.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  saving.value = true
  try {
    if (editingAdmin.value) {
      const data: {
        displayName?: string
        password?: string
        status?: 'active' | 'disabled'
        roleIds?: string[]
      } = {
        displayName: adminForm.displayName.trim(),
        status: adminForm.status,
        roleIds: adminForm.roleIds,
      }
      if (adminForm.password) data.password = adminForm.password
      await updateAdmin(editingAdmin.value.id, data)
      ElMessage.success('管理员已保存')
    } else {
      if (!/^[A-Za-z0-9_.-]{2,40}$/.test(adminForm.username)) {
        ElMessage.warning('登录名只能使用字母、数字、下划线、点和短横线，2 到 40 位')
        return
      }
      if (adminForm.password.length < 8) {
        ElMessage.warning('密码至少 8 位')
        return
      }
      await createAdmin({
        username: adminForm.username,
        password: adminForm.password,
        displayName: adminForm.displayName.trim(),
        roleIds: adminForm.roleIds,
      })
      ElMessage.success('管理员已创建')
    }
    adminDialogVisible.value = false
    await loadAll()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function openCreateRole() {
  editingRole.value = null
  Object.assign(roleForm, { code: '', name: '', permissions: [] })
  roleDialogVisible.value = true
}

function openEditRole(role: AdminRoleItem) {
  editingRole.value = role
  Object.assign(roleForm, {
    code: role.code,
    name: role.name,
    permissions: [...role.permissions],
  })
  roleDialogVisible.value = true
}

async function saveRole() {
  if (!roleForm.name.trim()) {
    ElMessage.warning('请输入角色名称')
    return
  }
  if (!editingRole.value && !/^[a-z][a-z0-9_.-]{1,39}$/.test(roleForm.code)) {
    ElMessage.warning('角色编码需以小写字母开头，可包含数字、下划线、点和短横线')
    return
  }
  saving.value = true
  try {
    if (editingRole.value) {
      await updateRole(editingRole.value.id, {
        name: roleForm.name.trim(),
        permissions: roleForm.permissions,
      })
      ElMessage.success('角色已保存')
    } else {
      await createRole({
        code: roleForm.code,
        name: roleForm.name.trim(),
        permissions: roleForm.permissions,
      })
      ElMessage.success('角色已创建')
    }
    roleDialogVisible.value = false
    await loadAll()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function removeRole(role: AdminRoleItem) {
  try {
    await ElMessageBox.confirm(
      `确认删除角色「${role.name}」？仍被管理员使用的角色不能删除。`,
      '删除角色',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteRole(role.id)
    ElMessage.success('角色已删除')
    await loadAll()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="page" v-loading="loading">
    <header class="page-head">
      <div>
        <h1 class="page-title">管理员与角色</h1>
        <p class="page-subtitle">
          权限按角色分配，接口每次请求实时校验；前端隐藏按钮只是体验优化。
        </p>
      </div>
      <el-button :icon="Refresh" @click="loadAll">刷新</el-button>
    </header>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="管理员" name="admins">
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索登录名或显示名"
            clearable
            style="width: 220px"
            @keyup.enter="loadAll"
            @clear="loadAll"
          />
          <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px" @change="loadAll">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
          <el-button :icon="Search" @click="loadAll">查询</el-button>
          <el-button type="primary" :icon="Plus" @click="openCreateAdmin">新增管理员</el-button>
        </div>

        <el-table :data="admins" border stripe>
          <el-table-column prop="username" label="登录名" min-width="130" />
          <el-table-column prop="displayName" label="显示名" min-width="120" />
          <el-table-column label="角色" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="role in row.roles" :key="role.id" size="small" class="tag">
                {{ role.name }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最近登录" width="160">
            <template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditAdmin(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="角色" name="roles">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="openCreateRole">新增角色</el-button>
        </div>
        <el-table :data="roles" border stripe>
          <el-table-column prop="code" label="角色编码" min-width="150" />
          <el-table-column prop="name" label="名称" min-width="130" />
          <el-table-column label="权限" min-width="300">
            <template #default="{ row }">
              <el-tag v-for="code in row.permissions" :key="code" size="small" class="tag" type="info">
                {{ permissionLabel[code] || code }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="管理员数" width="100">
            <template #default="{ row }">{{ row.adminCount }}</template>
          </el-table-column>
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag :type="row.builtin ? 'warning' : 'info'" size="small">
                {{ row.builtin ? '内置' : '自定义' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEditRole(row)">编辑</el-button>
              <el-button v-if="!row.builtin" link type="danger" @click="removeRole(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="adminDialogVisible"
      :title="editingAdmin ? '编辑管理员' : '新增管理员'"
      width="520px"
    >
      <el-form label-width="90px">
        <el-form-item label="登录名">
          <el-input v-model="adminForm.username" :disabled="Boolean(editingAdmin)" maxlength="40" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="adminForm.displayName" maxlength="40" />
        </el-form-item>
        <el-form-item :label="editingAdmin ? '重置密码' : '初始密码'">
          <el-input
            v-model="adminForm.password"
            type="password"
            show-password
            :placeholder="editingAdmin ? '留空表示不修改' : '至少 8 位'"
          />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="adminForm.roleIds" multiple style="width: 100%">
            <el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingAdmin" label="状态">
          <el-radio-group v-model="adminForm.status">
            <el-radio value="active">启用</el-radio>
            <el-radio value="disabled">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adminDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAdmin">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="roleDialogVisible"
      :title="editingRole ? '编辑角色' : '新增角色'"
      width="560px"
    >
      <el-form label-width="90px">
        <el-form-item label="角色编码">
          <el-input v-model="roleForm.code" :disabled="Boolean(editingRole)" maxlength="40" />
        </el-form-item>
        <el-form-item label="角色名称">
          <el-input v-model="roleForm.name" maxlength="40" />
        </el-form-item>
        <el-form-item label="权限点">
          <el-checkbox-group v-model="roleForm.permissions" class="permission-grid">
            <el-checkbox v-for="item in permissions" :key="item.code" :value="item.code">
              {{ item.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
}

.tag {
  margin: 0 4px 4px 0;
}

.permission-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  width: 100%;
}
</style>
