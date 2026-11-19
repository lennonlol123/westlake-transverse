# 用 GitHub Desktop 发布

本地仓库已经连接到：
https://github.com/lennonlol123/westlake-transverse

1. 打开 GitHub Desktop，登录你的 GitHub 账户。
2. 菜单 **File → Add Local Repository… → Choose…**，选择本目录
   `westlake-transverse`，然后点击 **Add Repository**。
3. 核对仓库名为 `westlake-transverse`、分支为 `main`。代码已提交到本地，
   点击 **Push origin** 将提交上传。如果 Desktop 先显示 **Fetch origin**，
   先点击一次，再推送本地提交。
4. 打开仓库网页的 **Settings → Pages**，将 **Source** 改为 **GitHub Actions**。
5. 在 **Actions** 中打开 **Build and publish playable TransVerse**。
   如果最早一次运行因为尚未启用 Pages 而失败，启用后选择 **Re-run all jobs**；
   也可用 **Run workflow** 手动运行。
6. 构建和部署都显示绿色后，试玩地址是：
   https://lennonlol123.github.io/westlake-transverse/

不会用到 API key 或仓库 secrets。无需上传整个 agii 项目，不要添加原始实验记录。
源码和素材都已包含在这个独立仓库中；`dist/` 是本机构建输出，由工作流重新生成。

## 本机先试

```sh
python3 tools/build_site.py
python3 tools/check_release.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory dist
```

浏览器打开 http://127.0.0.1:8000/。不要双击 HTML 文件打开。
