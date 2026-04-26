{
  description = "lxc-gh-runners dev shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            python312
            uv
            sqlite
            jq
            gh
            git
          ];

          shellHook = ''
            export UV_PYTHON=${pkgs.python312}/bin/python3.12
            echo "lxc-gh-runners dev shell — python $(python3 --version), uv $(uv --version)"
          '';
        };
      });
}
