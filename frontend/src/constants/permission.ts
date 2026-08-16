/** 权限码与角色权限映射（镜像后端 RBAC，见 src/models/role.py 与 init_mysql.sql）。
 * 前端只做菜单/按钮显隐，后端仍是最终裁决。 */
import type { Role } from '@/types/auth'

export type PermissionCode =
  | 'upload'
  | 'create_task'
  | 'view_report'
  | 'confirm'
  | 'manage_regulations'
  | 'manage_rules'
  | 'manage_users'
  | 'monitor'

export const ROLE_PERMISSIONS: Record<Role, PermissionCode[]> = {
  admin: [
    'upload',
    'create_task',
    'view_report',
    'confirm',
    'manage_regulations',
    'manage_rules',
    'manage_users',
    'monitor',
  ],
  reviewer: ['upload', 'create_task', 'view_report', 'confirm'],
  viewer: ['view_report'],
}
