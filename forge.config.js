const { FusesPlugin } = require('@electron-forge/plugin-fuses');
const { FuseV1Options, FuseVersion } = require('@electron/fuses');

module.exports = {
  packagerConfig: {
    asar: true,
    appBundleId: 'com.cristinakity.offlinestardewvalleywiki',
    executableName: 'offline-stardew-valley-wiki',
    icon: 'src/favicon',
    extraResource: [
      'src/stardewvalleywiki.com/mediawiki/extensions/StardewValley/images/stardewbackground.png',
      'src/flags',
      ...(process.env.WIKI_CONTENT_PATH ? [process.env.WIKI_CONTENT_PATH] : []),
    ],
    ignore: [
      /^\/src($|\/)/,
      /^\/wiki_updater($|\/)/,
      /^\/tests($|\/)/,
      /^\/\.local-data($|\/)/,
      /^\/compose.*\.yml$/,
      /^\/Containerfile/,
      /^\/pyproject\.toml$/,
    ],
  },
  rebuildConfig: {},
  makers: [
    {
      name: '@electron-forge/maker-squirrel',
      config: {},
    },
    {
      name: '@electron-forge/maker-zip',
      platforms: ['linux', 'win32'],
    },
    {
      name: '@electron-forge/maker-deb',
      config: {
        options: {
          maintainer: 'Cristina Carrasco',
          homepage: 'https://github.com/cristinakity/offline-stardew-valley-wiki'
        }
      },
    },
    {
      name: '@electron-forge/maker-rpm',
      config: {
        options: {
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
