-- Eternal2x Resolve Script Panel (Workspace > Scripts)
-- Compact UI: 4 actions + 1 sensitivity slider

local function script_dir()
    local info = debug.getinfo(1, "S")
    local src = info.source or ""
    if src:sub(1, 1) == "@" then
        src = src:sub(2)
    end
    local norm = src:gsub("\\", "/")
    return norm:match("(.*/)")
end

local function trim_trailing_sep(path)
    if not path then return "" end
    local out = path:gsub("[/\\]+$", "")
    return out
end

local function read_conf(path)
    local conf = {}
    local f = io.open(path, "r")
    if not f then
        return conf
    end
    for line in f:lines() do
        local k, v = line:match("^%s*([^=]+)%s*=%s*(.-)%s*$")
        if k and v then
            conf[k] = v
        end
    end
    f:close()
    return conf
end

local function parse_bool(value, default_value)
    if value == nil then
        return default_value
    end
    local s = tostring(value):lower()
    if s == "1" or s == "true" or s == "yes" or s == "on" then
        return true
    end
    if s == "0" or s == "false" or s == "no" or s == "off" then
        return false
    end
    return default_value
end

local function shell_quote(s)
    if not s then return "" end
    if package.config:sub(1, 1) == "\\" then
        -- cmd.exe escaping: double internal quotes
        return '"' .. s:gsub('"', '""') .. '"'
    end
    return '"' .. s:gsub('"', '\\"') .. '"'
end

local function run_command(cmd)
    print("[Eternal2x] " .. cmd)
    return os.execute(cmd)
end

local function is_windows()
    return package.config:sub(1, 1) == "\\"
end

local function get_selected_clip_path(resolve)
    local project = resolve:GetProjectManager():GetCurrentProject()
    if not project then return nil, "No active project." end
    local timeline = project:GetCurrentTimeline()
    if not timeline then return nil, "No active timeline." end

    local items = nil
    if timeline.GetSelectedItems then
        items = timeline:GetSelectedItems()
    end

    local item = nil
    if items and type(items) == "table" then
        for _, v in pairs(items) do
            item = v
            break
        end
    end
    if not item and timeline.GetCurrentVideoItem then
        item = timeline:GetCurrentVideoItem()
    end
    if not item then return nil, "No selected clip." end

    local mpi = item:GetMediaPoolItem()
    if not mpi then return nil, "No media pool item for clip." end
    local props = mpi:GetClipProperty() or {}
    local path = props["File Path"]
    if not path or path == "" then
        return nil, "Clip file path not available."
    end
    return path, nil
end

local function get_resolve()
    local ok, bmd = pcall(require, "DaVinciResolveScript")
    if not ok or not bmd then
        return nil, "Could not import DaVinciResolveScript."
    end
    local resolve = bmd.scriptapp("Resolve")
    if not resolve then
        return nil, "Could not connect to Resolve."
    end
    return resolve, nil
end

local ui = fu.UIManager
local disp = bmd.UIDispatcher(ui)

local root = trim_trailing_sep(script_dir() or "")
local conf = read_conf((root ~= "" and (root .. "/") or "") .. "Eternal2x.conf")
local REPO_ROOT = trim_trailing_sep(conf["repo_root"] or root or "")
local PYTHON = conf["python"] or (is_windows() and "python" or "python3")
local UPDATE_URL = conf["update_url"] or ""
local AUTO_UPDATE = parse_bool(conf["auto_update"], true)

local win = disp:AddWindow({
    ID = "Eternal2x",
    WindowTitle = "Eternal2x",
    Geometry = {100, 100, 380, 320},
    StyleSheet = [[
        QWidget {
            background-color: #101722;
            color: #eaf2ff;
            font-size: 12px;
        }
        QLabel#Title {
            font-size: 16px;
            font-weight: 700;
            color: #f4fbff;
            padding-bottom: 2px;
        }
        QLabel#SubTitle {
            color: #8fb2d6;
            padding-bottom: 8px;
        }
        QPushButton {
            background-color: #1f334d;
            border: 1px solid #4b78ab;
            border-radius: 7px;
            min-height: 30px;
            padding: 6px 8px;
            font-weight: 600;
        }
        QPushButton:hover { background-color: #29456b; }
        QPushButton:pressed { background-color: #1a2f4d; }
        QSlider::groove:horizontal {
            height: 6px;
            border-radius: 3px;
            background: #2a3c55;
        }
        QSlider::handle:horizontal {
            width: 14px;
            background: #ff8a3d;
            border: 1px solid #ffb17a;
            border-radius: 7px;
            margin: -5px 0;
        }
        QLabel#Status {
            background-color: #0b111a;
            border: 1px solid #334a68;
            border-radius: 6px;
            padding: 7px;
            color: #b7cae2;
        }
    ]]
}, ui:VGroup{
    ui:Label{ID="Title", Text="Eternal2x", ObjectName="Title"},
    ui:Label{ID="SubTitle", Text="DaVinci Resolve Smart Upscale", ObjectName="SubTitle"},
    ui:Button{ID="DetectBtn", Text="Detect"},
    ui:Button{ID="CutFrameBtn", Text="Sequence"},
    ui:Button{ID="RegroupBtn", Text="Regroup"},
    ui:Button{ID="UpscaleBtn", Text="Upscale and Interpolate"},
    ui:Button{ID="UpdateBtn", Text="Check for Updates"},
    ui:Label{ID="SensLabel", Text="Interpolate Sensitivity: 0.20"},
    ui:Slider{ID="SensSlider", Orientation="Horizontal", Minimum=0, Maximum=100, Value=20},
    ui:Label{ID="Status", Text="Ready.", ObjectName="Status", WordWrap=true},
})

local items = win:GetItems()

function win.On.Eternal2x.Close(ev)
    disp:ExitLoop()
end

local function set_status(msg)
    local line = msg or ""
    if items and items.Status then
        items.Status.Text = line
    end
    print("[Eternal2x] " .. line)
end

local function sensitivity_value()
    local v = 20
    if items and items.SensSlider and items.SensSlider.Value then
        v = items.SensSlider.Value
    end
    return v / 100.0
end

function win.On.SensSlider.ValueChanged(ev)
    local v = sensitivity_value()
    if items and items.SensLabel then
        items.SensLabel.Text = string.format("Interpolate Sensitivity: %.2f", v)
    end
end

local function build_command(module_name, extra_args)
    local args = extra_args or ""
    if is_windows() then
        return "cd /d " .. shell_quote(REPO_ROOT)
            .. " && " .. shell_quote(PYTHON)
            .. " -m " .. module_name
            .. args
    end
    return "cd " .. shell_quote(REPO_ROOT)
        .. " && " .. shell_quote(PYTHON)
        .. " -m " .. module_name
        .. args
end

local function run_stage(stage_label, module_name, extra_args)
    if REPO_ROOT == "" then
        set_status("Missing repo root. Reinstall using Installer/install_eternal2x.py.")
        return
    end
    set_status(stage_label .. " running...")
    local ok = run_command(build_command(module_name, extra_args))
    if ok == true or ok == 0 then
        set_status(stage_label .. " finished.")
    else
        set_status(stage_label .. " failed. Check Console for details.")
    end
end

local function run_update(auto_mode)
    if REPO_ROOT == "" then
        set_status("Missing repo root. Reinstall using Installer/install_eternal2x.py.")
        return
    end
    if UPDATE_URL == "" then
        set_status("No update URL configured.")
        return
    end
    local args = " --meta-url " .. shell_quote(UPDATE_URL)
    if auto_mode then
        args = args .. " --auto"
    end
    if not auto_mode then
        set_status("Checking for updates...")
    end
    local ok = run_command(build_command("Stages.resolve_update", args))
    if not auto_mode then
        if ok == true or ok == 0 then
            set_status("Update check complete. See Console for details.")
        else
            set_status("Update failed. See Console for details.")
        end
    end
end

function win.On.DetectBtn.Clicked(ev)
    local resolve, err = get_resolve()
    if not resolve then
        set_status(err)
        return
    end
    local path, perr = get_selected_clip_path(resolve)
    if not path then
        set_status(perr)
        return
    end
    local v = sensitivity_value()
    local args = " --video " .. shell_quote(path)
        .. " --sensitivity " .. string.format("%.4f", v)
    run_stage("Detect", "Stages.resolve_detect_markers", args)
end

function win.On.CutFrameBtn.Clicked(ev)
    run_stage("Sequence", "Stages.resolve_cut_and_sequence", "")
end

function win.On.RegroupBtn.Clicked(ev)
    run_stage("Regroup", "Stages.resolve_regroup", "")
end

function win.On.UpscaleBtn.Clicked(ev)
    local v = sensitivity_value()
    local args = " --sensitivity " .. string.format("%.4f", v)
    run_stage("Upscale and Interpolate", "Stages.resolve_upscale_interpolate", args)
end

function win.On.UpdateBtn.Clicked(ev)
    run_update(false)
end

win:Show()
if REPO_ROOT == "" then
    set_status("Warning: no config found. Run installer script.")
else
    set_status("Ready. Repo: " .. REPO_ROOT)
    if AUTO_UPDATE then
        run_update(true)
    end
end
disp:RunLoop()
