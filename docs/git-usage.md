# Git 使用说明

项目仓库默认分支为`main`，可以保存在任意目录。
Git从PATH发现，VS Code工作区不固定某台电脑的Git安装路径。

安装Git后，在项目根目录打开终端并检查当前修改：

```bat
git status
git diff
```

完成一项修改后，把相应文件加入版本记录，例如：

```bat
git add scripts/check_environment.py
git commit -m "更新环境检查"
git log --oneline -5
```

提交作者姓名和邮箱是各自电脑上的Git用户设置，不随本仓库分发。
协作者应使用自己的提交身份；作者信息不代表已经登录GitHub。

源代码、文档、环境清单和锁定文件纳入版本管理；`data/`、`output/`、
`tmp/`、虚拟环境及编译生成文件按照 `.gitignore` 排除。
原始数据和实验结果需要单独备份。

`.gitattributes` 统一源文件换行符，并将图像、PDF 和科学数据格式标记为二进制。
仓库尚未设置远程地址；以后如需多人协作，再连接团队选定的代码托管仓库。
