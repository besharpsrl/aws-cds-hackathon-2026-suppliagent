import { execFileSync } from 'node:child_process';
import { cpSync, rmSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { AssetHashType, DockerImage, type BundlingOptions } from 'aws-cdk-lib';

/** Repository root: the uv workspace (pyproject.toml + uv.lock). */
export const REPO_ROOT = fileURLToPath(new URL('../../../', import.meta.url));

export interface UvBundlingProps {
  /** uv workspace package whose locked dependencies are installed, e.g. `suppliagent-agent`. */
  readonly package: string;
  /** Workspace sources copied into the asset root: repo-relative source → destination name. */
  readonly sources: Readonly<Record<string, string>>;
  /** Packages provided by the platform (Lambda runtime / Powertools layer), not installed. */
  readonly omit?: readonly string[];
}

/**
 * Asset options that bundle a Python package locally, without Docker: dependencies pinned by uv.lock,
 * installed for ARM64 Linux (Lambda and AgentCore Runtime are ARM64), plus the workspace sources.
 * Requires `uv` on PATH at synth time; skipped when bundling is off (`aws:cdk:bundling-stacks`).
 */
export function uvBundling(props: UvBundlingProps): {
  bundling: BundlingOptions;
  assetHashType: AssetHashType;
} {
  return {
    assetHashType: AssetHashType.OUTPUT,
    bundling: {
      // ponytail: required by the type, never pulled because local bundling always succeeds.
      image: DockerImage.fromRegistry('scratch'),
      local: {
        tryBundle(outputDir: string) {
          const requirements = path.join(outputDir, 'requirements.txt');
          const uv = (args: string[]) =>
            execFileSync('uv', args, { cwd: REPO_ROOT, stdio: ['ignore', 'ignore', 'inherit'] });
          uv([
            'export',
            ...['--package', props.package, '--frozen', '--no-dev'],
            ...['--no-emit-workspace', '--no-header', '--no-annotate'],
            ...(props.omit ?? []).flatMap((name) => ['--no-emit-package', name]),
            ...['--output-file', requirements],
          ]);
          // Hashes from uv.lock and no re-resolution: exactly the locked wheels, nothing else.
          uv([
            ...['pip', 'install', '--quiet', '--target', outputDir, '--requirement', requirements],
            ...['--python-platform', 'aarch64-manylinux2014', '--python-version', '3.12'],
            ...['--only-binary=:all:', '--require-hashes', '--no-deps'],
          ]);
          rmSync(requirements);
          for (const [source, destination] of Object.entries(props.sources)) {
            cpSync(path.join(REPO_ROOT, source), path.join(outputDir, destination), {
              recursive: true,
              filter: (file) => !file.includes('__pycache__'),
            });
          }
          return true;
        },
      },
    },
  };
}
