# 项目记忆

本目录只保存跨任务可复用、且 Git 历史、ADR、产品设计或技术路线不能直接替代的工程记忆。

## 写入门槛

- 一条记忆只描述一个事实或一个排障入口；
- 必须来自已经发生并得到证据支持的问题，禁止为“以后可能遇到”预建空壳；
- 不记录“完成了什么功能”或普通进度；
- 文件名使用简短 kebab-case，并在本文件追加一行检索 hook。

## 固定结构

```markdown
# <一句话事实>

**根因**：正确判读公式、约束或结论。

**坑**：本次实际浪费时间或导致误判的路线。

**杠杆**：下次遇到同类问题时最快的检查入口、命令或文件。
```

事故排查类可改为“症状 / 判读 / 动作”，但仍然一事一文件。

## 记忆索引

- [Linux 浏览器缓存路径必须贯穿安装与运行](linux-browser-cache-path.md)
- [登录页必须显式切换到密码登录](password-login-mode.md)
- [JSON迁移只在容器边界解码](json-migration-container-boundary.md)
- [Patchright通用Error必须在适配器边界分类](patchright-error-classification.md)
- [浏览器Cookie空值不是Session结构缺失](browser-cookie-empty-value.md)
