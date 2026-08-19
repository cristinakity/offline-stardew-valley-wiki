const { FusesPlugin } = require('@electron-forge/plugin-fuses');
const { FuseV1Options, FuseVersion } = require('@electron/fuses');

const appSlug = 'offline-stardew-valley-wiki';
const productName = 'Offline Stardew Valley Wiki';

module.exports = {
  packagerConfig: {
    asar: true,
    name: productName,
    appBundleId: 'com.cristinakity.offlinestardewvalleywiki',
    executableName: appSlug,
    icon: 'desktop/assets/favicon',
    extraResource: [
      'desktop/assets/stardewbackground.png',
      'desktop/assets/flags',
      'desktop/content-release.json',
      'desktop/content-worker.js',
      'scripts/prepare-edition.mjs',
    ],
    ignore: [
      /^\/wiki_updater($|\/)/,
      /^\/tests($|\/)/,
      /^\/\.local-data($|\/)/,
      /^\/snapshot($|\/)/,
      /^\/compose.*\.yml$/,
      /^\/Containerfile/,
      /^\/pyproject\.toml$/,
    ],
  },
  rebuildConfig: {},
  makers: [
    {
      name: '@electron-forge/maker-squirrel',
      config: {
        name: appSlug.replaceAll('-', '_'),
        setupExe: `${appSlug}-setup.exe`,
      },
    },
    {
      name: '@electron-forge/maker-zip',
      platforms: ['linux', 'win32'],
    },
    {
      name: '@electron-forge/maker-deb',
      config: {
        options: {
          name: appSlug,
          productName,
          bin: appSlug,
          maintainer: 'Cristina Carrasco',
          homepage: 'https://github.com/cristinakity/offline-stardew-valley-wiki'
        }
      },
    },
    {
      name: '@electron-forge/maker-rpm',
      config: {
        options: {
          name: appSlug,
          productName,
          bin: appSlug,
          homepage: 'https://github.com/cristinakity/offline-stardew-valley-wiki'
        }
      },
    },
  ],
  plugins: [
    {
      name: '@electron-forge/plugin-auto-unpack-natives',
      config: {},
    },
    // Fuses are used to enable/disable various Electron functionality
    // at package time, before code signing the application
    new FusesPlugin({
      version: FuseVersion.V1,
      [FuseV1Options.RunAsNode]: false,
      [FuseV1Options.EnableCookieEncryption]: true,
      [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
      [FuseV1Options.EnableNodeCliInspectArguments]: false,
      [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
      [FuseV1Options.OnlyLoadAppFromAsar]: true,
    }),
  ],
  publishers: [
    {
      name: '@electron-forge/publisher-github',
      config: {
        repository: {
          owner: 'cristinakity',
          name: 'offline-stardew-valley-wiki'
        },
        prerelease: false,
        draft: true
      }
    }
  ]
};
