# Published optimized IPs

`nodes.txt` is the stable plain-text result file. Each line uses `IPv4:port#COUNTRY`, for example:

```text
192.120.242.23:443#DE
```

The example documents the naming format and is not a measured result. The file starts empty until the first successful optimization. A completed publication writes the best 100 ordinary results, followed by 10 additional verified Japanese results. Country codes are uppercase; `XX` denotes an unknown ordinary exit country.

The local application creates the text from its actual final ranking. The cloud validates the complete result package and checks that `nodes.txt` exactly matches `nodes.json` before committing this directory to GitHub. Insufficient results preserve the previous successful file.
