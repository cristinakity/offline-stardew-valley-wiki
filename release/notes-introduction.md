![Offline Stardew Valley Wiki](https://github.com/cristinakity/offline-stardew-valley-wiki/assets/2953184/980d8860-510c-43e9-9b78-d8b2031ad866)

We are excited to announce the release of Offline Stardew Valley Wiki v1.3.0!

Offline Stardew Valley Wiki is a cross-platform desktop application that lets Stardew Valley players browse the wiki without an Internet connection. Version 1.3.0 introduces a lighter application and a new first-run content installer: install the reader once, then choose exactly which languages you want to keep.

## Highlights

- Choose any combination of 12 supported wiki languages during setup.
- Change the application interface language independently from the installed wiki languages.
- Download and verify the approved wiki snapshot directly in the application, with progress, pause, resume, and cancellation controls.
- Import the same snapshot from a local file or USB drive for computers without Internet access.
- Keep the downloaded archive if you want to add more languages later without downloading it again.
- Browse, search, and use the selected wiki content completely offline after installation.
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

## Content integrity

This release uses immutable snapshot `20260811T015121Z-7206e5e0cacc`, containing 25,852 pages. It passed offline validation with zero broken internal links, zero required missing assets, and zero remote resources. Checksums, the exact OCI reference, and the full validation report are included with the release assets. Thirty optional source assets that were unavailable are documented in that report.

## Community project

Created and maintained by [Cristina Carrasco (@cristinakity)](https://github.com/cristinakity). This is an unofficial community project and is not affiliated with ConcernedApe or the Stardew Valley Wiki team.

If you find a problem or have a suggestion, please [open an issue](https://github.com/cristinakity/offline-stardew-valley-wiki/issues).

Thank you for your support!
