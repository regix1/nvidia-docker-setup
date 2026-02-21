/**
 * Converts Dolby Vision Profile 5 video to SDR using libplacebo with Vulkan.
 * 
 * Profile 5 uses DV's proprietary IPTPQc2 color space in the base layer.
 * Standard HDR-to-SDR tone-mapping (zscale/tonemap) cannot read this color
 * space and produces purple/green output. libplacebo is the only ffmpeg
 * filter that natively understands IPTPQc2 and applies the DV RPU reshaping
 * to produce correct colors.
 *
 * Pipeline: Decode → Vulkan upload → libplacebo tone-map → download → NVENC encode
 * Audio and subtitle streams are copied without re-encoding.
 *
 * Connect this to Output 3 of the "Detect DV Profile" script.
 *
 * @author regix
 * @version 3
 * @output Successfully converted to SDR
 */
function Script() {
    let ffmpeg = ToolPath("ffmpeg");
    if (!ffmpeg) return -1;

    let working = Flow.WorkingFile;
    Logger.ILog("DV Profile 5 to SDR: starting conversion");
    Logger.ILog("Input: " + working);

    let dir = System.IO.Path.GetDirectoryName(working);
    let nameNoExt = System.IO.Path.GetFileNameWithoutExtension(working);
    let output = System.IO.Path.Combine(dir, nameNoExt + "_sdr.mkv");

    // libplacebo filter: reads DV RPU metadata (apply_dovi=1 is default),
    // converts IPTPQc2 → BT.2020/PQ internally, then tone-maps to BT.709 SDR.
    // bt.2390 is the ITU-R recommended tone-mapping curve.
    let vf = [
        "libplacebo=tonemapping=bt.2390",
        "colorspace=bt709",
        "color_primaries=bt709",
        "color_trc=bt709",
        "format=yuv420p"
    ].join(":");

    let useNvenc = detectNvenc(ffmpeg);

    let args = [
        "-y",
        "-init_hw_device", "vulkan=vk",
        "-filter_hw_device", "vk",
        "-i", working,
        "-map", "0",
        "-vf", vf
    ];

    if (useNvenc) {
        args = args.concat(["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "20"]);
    } else {
        args = args.concat(["-c:v", "libx265", "-preset", "medium", "-crf", "20",
                            "-x265-params", "log-level=error"]);
    }

    args = args.concat([
        "-c:a", "copy",
        "-c:s", "copy",
        "-max_muxing_queue_size", "2048",
        output
    ]);

    Logger.ILog("Command: " + ffmpeg + " " + args.join(" "));

    let process = Flow.Execute({
        command: ffmpeg,
        argumentList: args
    });

    if (process.exitCode !== 0) {
        let stderr = process.standardError || process.output || "";
        if (stderr.length > 1500)
            stderr = stderr.substring(stderr.length - 1500);
        Logger.ELog("FFmpeg failed (exit " + process.exitCode + "):\n" + stderr);
        try { System.IO.File.Delete(output); } catch(e) {}
        return -1;
    }

    if (!System.IO.File.Exists(output)) {
        Logger.ELog("Output file not found: " + output);
        return -1;
    }

    let info = new System.IO.FileInfo(output);
    if (info.Length < 1000) {
        Logger.ELog("Output file too small (" + info.Length + " bytes), likely failed");
        try { System.IO.File.Delete(output); } catch(e) {}
        return -1;
    }

    Logger.ILog("Conversion complete: " + output);
    Logger.ILog("Output size: " + (info.Length / 1048576).toFixed(1) + " MB");

    Flow.SetWorkingFile(output);
    return 1;
}

/**
 * Tests whether hevc_nvenc is actually usable by running a minimal test encode.
 * Checking ldconfig alone is not enough — libcuda.so.1 may appear in the cache
 * but not be loadable by FFmpeg at runtime.
 */
function detectNvenc(ffmpeg) {
    let test = Flow.Execute({
        command: ffmpeg,
        argumentList: [
            "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.04",
            "-c:v", "hevc_nvenc", "-f", "null", "-"
        ]
    });

    if (test.exitCode === 0) {
        Logger.ILog("NVENC test encode succeeded — using hevc_nvenc");
        return true;
    }

    Logger.ILog("NVENC not usable — falling back to libx265 software encoder");
    let stderr = test.standardError || test.output || "";
    if (stderr.length > 0) {
        if (stderr.length > 500)
            stderr = stderr.substring(stderr.length - 500);
        Logger.ILog("NVENC test output: " + stderr);
    }
    return false;
}

/**
 * Resolves the full path to an external tool.
 * Checks in order: FileFlows Variables, 'which' command (Docker),
 * known install paths, and Flow.GetToolPath with case variants.
 */
function ToolPath(tool) {
    let varPath = Variables[tool];
    if (varPath && typeof varPath === "string" && varPath.length > 0) {
        Logger.ILog("Found " + tool + " via Variables['" + tool + "']: " + varPath);
        return varPath;
    }

    if (Flow.IsDocker) {
        let result = Flow.Execute({
            command: "which",
            argumentList: [tool]
        });
        if (result.exitCode === 0)
            return result.output.replace(/\n/, "");

        let knownPaths = {
            "ffprobe":    ["/usr/local/bin/ffprobe", "/usr/lib/jellyfin-ffmpeg/ffprobe"],
            "ffmpeg":     ["/usr/local/bin/ffmpeg", "/usr/lib/jellyfin-ffmpeg/ffmpeg"],
            "dovi_tool":  ["/bin/dovi_tool", "/usr/local/bin/dovi_tool"],
            "mkvmerge":   ["/usr/bin/mkvmerge"],
            "mkvextract": ["/usr/bin/mkvextract"]
        };

        if (knownPaths[tool]) {
            for (let i = 0; i < knownPaths[tool].length; i++) {
                if (System.IO.File.Exists(knownPaths[tool][i])) {
                    Logger.ILog("Found " + tool + " at: " + knownPaths[tool][i]);
                    return knownPaths[tool][i];
                }
            }
        }

        Logger.ELog(tool + " not found — install the required DockerMod");
        return null;
    }

    let toolPath = Flow.GetToolPath(tool);
    if (toolPath) return toolPath;

    let variants = {
        "ffmpeg":  ["FFmpeg", "Ffmpeg"],
        "ffprobe": ["FFprobe", "Ffprobe"]
    };
    if (variants[tool]) {
        for (let i = 0; i < variants[tool].length; i++) {
            toolPath = Flow.GetToolPath(variants[tool][i]);
            if (toolPath) return toolPath;
        }
    }

    if (tool === "ffprobe") {
        let ffmpegPath = Flow.GetToolPath("FFmpeg") || Flow.GetToolPath("ffmpeg");
        if (ffmpegPath) {
            let dir = System.IO.Path.GetDirectoryName(ffmpegPath);
            let probePath = System.IO.Path.Combine(dir, Flow.IsWindows ? "ffprobe.exe" : "ffprobe");
            if (System.IO.File.Exists(probePath)) return probePath;
        }
    }

    Logger.ELog(tool + " not found — configure it in Settings > Variables");
    return null;
}
