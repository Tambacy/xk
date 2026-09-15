# 免责声明

> **一句话版本**：这是个人学习项目，与任何高校没有任何关系；用它选课可能违反
> 你所在学校的规定并导致账号或选课结果受影响，**后果由使用者自行承担**。

最后更新：2026-09-15 · 适用于 v0.3.0 及之后的所有版本

---

## 一、与任何学校均无关联

- 本项目是**个人独立项目**，与任何高校、学校大学教务处、教学研究与培训中心、
  信息化技术中心，以及任何院系、任何教学管理机构**均无任何关系**。
- 本项目**未获得上述任何机构的授权、认可、支持或赞助**。
- 本项目是个人工具，**不代表任何机构**。
- 统一身份认证系统、选课系统等均为学校的资产与信息系统，本项目
  **不对其做任何修改、不绕过其任何限制、不获取任何未授权的数据**。

## 二、使用风险由使用者自行承担

自动化选课工具在许多高校**属于违规行为**。使用本软件可能带来的后果
包括但不限于：

- 违反学校关于选课的规定，导致**选课结果被取消、成绩记为无效**；
- 账号被风控系统识别，导致**登录受限、被要求额外验证**；
- 受到**纪律处分**；
- 因程序缺陷、网络故障、系统改版、选课规则变化等原因，导致
  **错过选课时机、误退已选课程、或选到非预期的课程**；
- 因高频请求**给教务系统造成压力**，影响其他同学正常使用。

**以上及任何其他后果，均由使用者自行承担。作者不承担任何直接或间接责任。**

请在**确认你所在学校允许**之后再使用本软件。若不确定，请不要使用。

## 三、使用限制

**禁止**：

1. 任何形式的**商业用途** —— 包括但不限于收费代抢、有偿分享、打包售卖、
   以本软件为基础提供付费服务；
2. 将本软件部署为**面向他人的服务**；
3. **大规模分发**安装包，或诱导、组织他人使用 —— 这会把风险从个人扩大到群体，
   也会给教务系统带来集中压力；
4. 移除、遮蔽或修改本声明、`LICENSE` 以及软件界面中的相关声明；
5. 用于任何违反法律法规、学校规定或公序良俗的场景。

**允许**（详见 [LICENSE](LICENSE)）：个人学习、研究与安全审计；在**本人账号**上
自用；为非自用目的阅读与修改源代码。

## 四、关于你的账号与密码

这一点请你放心，也请你留意：

- 密码使用 **Windows DPAPI** 加密后存放在**本机**，密钥由操作系统按
  「当前 Windows 账户 + 当前机器」派生 —— 换账户或换电脑都解不开；
- **程序不会把学号、密码或任何个人信息发送到学校官方系统之外的任何地方**；
- **没有遥测、没有统计上报、没有远程配置、没有自动更新**；
- 但反过来说：本软件需要你的统一身份认证凭据才能工作。请只在**你本人**的
  设备上运行，并在不使用时通过界面上的「清除本机已保存的账号密码」清除凭据。

## 五、无担保

本软件按「**现状**」提供，不附带任何明示或暗示的担保，包括但不限于对
**适销性、特定用途适用性、不侵权**的担保。作者不保证本软件无缺陷、
不保证其持续可用、不保证任何选课结果。

学校系统随时可能改版，本项目**可能失效且不保证及时修复**。

## 六、权利方如有异议

如果你是本项目所涉及系统的权利方，或认为本项目存在不当之处，
请通过本仓库的 [Issues](../../issues) 或私密漏洞报告渠道联系。

作者会**立即配合处理**，包括但不限于：下架仓库、删除发行版、
调整说明措辞。**不需要任何前置程序，直接说明诉求即可。**

## 七、生效

**使用、复制、修改或分发本软件，即视为你已阅读、理解并同意本声明与
[LICENSE](LICENSE) 的全部内容。** 若不同意，请立即停止使用并删除本软件。

---

## English Summary

This is a **personal, non-commercial study project** with **no affiliation
whatsoever** with any university or any of its departments. It is neither
authorized nor endorsed by them.

Automating course registration **may violate your school's rules** and could
result in cancelled registrations, account restrictions, or disciplinary
action. **You use this software entirely at your own risk.** The author accepts
no liability for any consequences.

Commercial use, operating it as a service for others, and mass redistribution
are **prohibited**. See [LICENSE](LICENSE) for the full terms.

Credentials are encrypted locally with Windows DPAPI and are never transmitted
anywhere except to your school's official systems. There is no telemetry.

If you are a rights holder and object to this project, please open an issue —
the author will comply promptly.
