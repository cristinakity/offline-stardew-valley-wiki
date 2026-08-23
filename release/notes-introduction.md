![Offline Stardew Valley Wiki](https://github.com/cristinakity/offline-stardew-valley-wiki/assets/2953184/980d8860-510c-43e9-9b78-d8b2031ad866)

We are excited to announce the release of Offline Stardew Valley Wiki v2.0.0!

Offline Stardew Valley Wiki is a cross-platform desktop application that lets Stardew Valley players browse the wiki without an Internet connection. Version 2.0.0 introduces a lighter application and a new first-run content installer: install the reader once, then choose exactly which languages you want to keep.

## Highlights

- Choose any combination of 12 supported wiki languages during setup.
- Change the application interface language independently from the installed wiki languages.
- Download and verify the approved wiki snapshot directly in the application, with progress, pause, resume, and cancellation controls.
- Import the same snapshot from a local file or USB drive for computers without Internet access.
- Keep the downloaded archive if you want to add more languages later without downloading it again.
- Browse, search, and use the selected wiki content completely offline after installation.
- Change the wiki and application interface together by selecting a language flag.
- See the installed application version, content version, snapshot date, and languages from the About window.
- Open a localized getting-started guide from the new `?` button.
- View project, creator, source-code, download, license, and community information from the new About window.

## Downloads

### Windows

- **Setup executable** — recommended for most users.
- **Portable ZIP** — extract it and run the application without an installer.

### Linux

- **DEB** — for Debian, Ubuntu, and compatible distributions.
- **RPM** — for Fedora, RHEL, openSUSE, and compatible distributions.
- **Portable ZIP** — extract it and run the application directly.

On first launch, the application downloads one approved multilingual snapshot (about 644 MiB), verifies it, and installs only your selected languages. The preparation step can require up to 7 GiB of temporary free space. Once it finishes, the selected wiki works without Internet. You may also download the attached `.tar.zst` snapshot separately and select **Import from file / USB**.

## Easy installation

### Windows (recommended)

1. Under **Assets**, download **`offline-stardew-valley-wiki-setup.exe`**.
2. Double-click the downloaded file and follow the installation prompts.
3. Open **Offline Stardew Valley Wiki** from the Start menu or desktop shortcut.

### Ubuntu, Debian, or Linux Mint

1. Under **Assets**, download **`offline-stardew-valley-wiki_2.0.0_amd64.deb`**.
2. Double-click the downloaded file and choose **Install** in your software manager.
3. Open **Offline Stardew Valley Wiki** from your applications menu.

### Fedora, RHEL, or openSUSE

Download **`offline-stardew-valley-wiki-2.0.0-1.x86_64.rpm`** under **Assets**, open it with your software manager, and choose **Install**.

### First launch

1. Choose the language for the application menus.
2. Select the wiki languages you want available offline.
3. Click **Download and install** and keep the application open while it prepares the wiki.
4. When installation finishes, open the wiki and use it without Internet.

That is all most users need to do. You **do not** need to download the `.tar.zst`, JSON, or `SHA256SUMS` files manually. The portable ZIP packages and **Import from file / USB** option are alternatives for users who do not want an installer or need to move the content to an offline computer.

## Content integrity

This release uses immutable snapshot `20260811T015121Z-7206e5e0cacc`, containing 25,852 pages. It passed offline validation with zero broken internal links, zero required missing assets, and zero remote resources. Checksums, the exact OCI reference, and the full validation report are included with the release assets. Thirty optional source assets that were unavailable are documented in that report.

## Community project

Created and maintained by [Cristina Carrasco (@cristinakity)](https://github.com/cristinakity). This is an unofficial community project and is not affiliated with ConcernedApe or the Stardew Valley Wiki team.

If you find a problem or have a suggestion, please [open an issue](https://github.com/cristinakity/offline-stardew-valley-wiki/issues).

Thank you for your support!
