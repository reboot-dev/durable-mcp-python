{
  description = "nix for durable mcp";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python
            uv
            stdenv.cc.cc.lib
            pdftk
          ];

          shellHook = ''
            export UV_PYTHON="${python}/bin/python"
            export UV_PYTHON_DOWNLOADS="never"
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:$LD_LIBRARY_PATH"

            # Set custom prompt with project path and git branch.
            git_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "no-git")
            export PS1='\[\033[1;34m\]mcp\[\033[0m\] \[\033[1;34m\]code\[\033[0m\] \[\033[1;34m\]storm\[\033[0m\]  \[\033[1;32m\]$git_branch\[\033[0m\] \[\033[1;31m\]❯\[\033[0m\] '

            echo "Durable MCP development environment"
            echo "Python: ${python}/bin/python"
            echo "UV available at: $(which uv)"
            echo ""
            echo "To install dependencies: uv sync"
          '';
        };
      }
    );
}
