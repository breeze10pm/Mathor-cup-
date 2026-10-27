# Git 使用说明

已安装独立的 Git for Windows，项目本地仓库位于
`D:\HCX\Mathor cup`，默认分支是 `main`。
VS Code 已配置使用这份 Git。

安装后重新打开终端，进入项目并检查当前修改：

```bat
cd /d "D:\HCX\Mathor cup"
git status
git diff
```

完成一项修改后，把相应文件加入版本记录，例如：

```bat
git add scripts/check_environment.py
git commit -m "更新环境检查"
git log --oneline -5
```

提交作者姓名和邮箱已经按用户提供的信息写入 Git 用户设置。
该身份用于标记提交，不代表已经登录 GitHub。

源代码、文档、环境清单和锁定文件纳入版本管理；`data/`、`output/`、
`tmp/`、虚拟环境及编译生成文件按照 `.gitignore` 排除。
原始数据和实验结果需要单独备份。

`.gitattributes` 统一源文件换行符，并将图像、PDF 和科学数据格式标记为二进制。
仓库尚未设置远程地址；以后如需多人协作，再连接团队选定的代码托管仓库。
