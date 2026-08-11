const { FusesPlugin } = require('@electron-forge/plugin-fuses');
const { FuseV1Options, FuseVersion } = require('@electron/fuses');

const supportedEditions = new Set(['multilingual', 'en', 'es', 'de', 'fr', 'it', 'ja', 'ko', 'hu', 'pt', 'ru', 'tr', 'zh']);
const requestedEdition = (process.env.WIKI_EDITION || 'multilingual').toLowerCase();
const edition = requestedEdition === 'full' ? 'multilingual' : requestedEdition;
if (!supportedEditions.has(edition)) throw new Error(`Unsupported WIKI_EDITION: ${edition}`);
const isMultilingual = edition === 'multilingual';
const editionSuffix = isMultilingual ? '' : `-${edition}`;
const appSlug = `offline-stardew-valley-wiki${editionSuffix}`;
const productName = `Offline Stardew Valley Wiki${isMultilingual ? '' : ` (${edition.toUpperCase()})`}`;

module.exports = {
  packagerConfig: {
    asar: true,
    name: productName,
    appBundleId: `com.cristinakity.offlinestardewvalleywiki${isMultilingual ? '' : `.${edition}`}`,
    executableName: appSlug,
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
