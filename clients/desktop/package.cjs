// Assemble the current host's portable Electron distribution using the locked runtime.
const fs = require('node:fs/promises');
const path = require('node:path');

async function packageApplication() {
  // Requiring electron also installs its matching runtime on first use.
  require('electron');
  const runtime = path.join(path.dirname(require.resolve('electron/package.json')), 'dist');
  const version = require('./package.json').version;
  const platformName = process.platform + '-' + process.arch;
  const output = path.resolve(
    process.argv[2] || path.join(__dirname, 'dist', 'yihe-' + version + '-' + platformName)
  );
  await fs.mkdir(path.dirname(output), { recursive: true });
  await fs.mkdir(output); // Preserve prior builds at an explicitly specified location.
  await fs.cp(runtime, output, { recursive: true, verbatimSymlinks: true });
  const resources =
    process.platform === 'darwin'
      ? path.join(output, 'Electron.app', 'Contents', 'Resources')
      : path.join(output, 'resources');
  const appPath = path.join(resources, 'app');
  await fs.mkdir(appPath);
  for (const file of ['main.cjs', 'source-preload.cjs', 'public-source.cjs', 'lead-calls.cjs', 'payment-links.cjs'])
    await fs.copyFile(path.join(__dirname, file), path.join(appPath, file));
  await fs.writeFile(
    path.join(appPath, 'package.json'),
    JSON.stringify(
      {
        name: 'yihe-care-desktop',
        productName: '安康医养平台',
        version,
        main: 'main.cjs',
      },
      null,
      2
    ) + '\n'
  );
  console.log('已生成 ' + platformName + ' 桌面应用：' + output);
}

packageApplication().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
