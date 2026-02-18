-- Eternal2x Resolve Script Panel (Workspace > Scripts)
-- Minimal UI: 4 buttons + 1 slider

local function script_dir()
    local info = debug.getinfo(1, "S")
    local src = info.source or ""
    if src:sub(1, 1) == "@" then
        src = src:sub(2)
    end
    return src:match("(.*/)")
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

local function shell_quote(s)
    if not s then return "" end
    return '"' .. s:gsub('"', '\\"') .. '"'
end

local function run_command(cmd)
    print("[Eternal2x] " .. cmd)
    return os.execute(cmd)
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

local root = script_dir() or ""
local conf = read_conf((root or "") .. "Eternal2x.conf")
local REPO_ROOT = conf["repo_root"] or ""
local PYTHON = conf["python"] or "python3"

local win = disp:AddWindow({
    ID = "Eternal2x",
    WindowTitle = "Eternal2x",
    Geometry = {100, 100, 340, 240},
    StyleSheet = [[
        QWidget { background-color: #0b1016; color: #e6f7ff; }
        QPushButton { background-color: #12323f; border: 1px solid #1b6a78; padding: 6px; }
        QPushButton:hover { background-color: #164654; }
        QSlider::groove:horizontal { height: 6px; background: #12323f; }
        QSlider::handle:horizontal { width: 14px; background: #2ad4c7; margin: -4px 0; }
        QLabel { color: #c7eef2; }
    ]]
}, ui:VGroup{
    ui:Button{ID="DetectBtn", Text="Detect"},
    ui:Button{ID="CutFrameBtn", Text="Cut and Frame"},
    ui:Button{ID="RegroupBtn", Text="Regroup"},
    ui:Button{ID="UpscaleBtn", Text="Upscale and Interpolate"},
    ui:Label{ID="SensLabel", Text="Interpolate Sensitivity: 0.20"},
    ui:Slider{ID="SensSlider", Orientation="Horizontal", Minimum=0, Maximum=100, Value=20},
})

function win.On.Eternal2x.Close(ev)
    disp:ExitLoop()
end

local function sensitivity_value()
    local v = win.SensSlider.Value or 20
    return v / 100.0
end

function win.On.SensSlider.ValueChanged(ev)
    local v = sensitivity_value()
    win.SensLabel.Text = string.format("Interpolate Sensitivity: %.2f", v)
end

function win.On.DetectBtn.Clicked(ev)
    if REPO_ROOT == "" then
        print("[Eternal2x] Missing repo_root in Eternal2x.conf.")
        return
    end
    local resolve, err = get_resolve()
    if not resolve then
        print("[Eternal2x] " .. err)
        return
    end
    local path, perr = get_selected_clip_path(resolve)
    if not path then
        print("[Eternal2x] " .. perr)
        return
    end
    local v = sensitivity_value()
    local cmd = "cd " .. shell_quote(REPO_ROOT)
        .. " && " .. shell_quote(PYTHON)
        .. " -m Stages.resolve_detect_markers"
        .. " --video " .. shell_quote(path)
        .. " --sensitivity " .. string.format("%.4f", v)
    run_command(cmd)
end

function win.On.CutFrameBtn.Clicked(ev)
    if REPO_ROOT == "" then
        print("[Eternal2x] Missing repo_root in Eternal2x.conf.")
        return
    end
    local cmd = "cd " .. shell_quote(REPO_ROOT)
        .. " && " .. shell_quote(PYTHON)
        .. " -m Stages.resolve_cut_and_frame"
    run_command(cmd)
end

function win.On.RegroupBtn.Clicked(ev)
    if REPO_ROOT == "" then
        print("[Eternal2x] Missing repo_root in Eternal2x.conf.")
        return
    end
    local cmd = "cd " .. shell_quote(REPO_ROOT)
        .. " && " .. shell_quote(PYTHON)
        .. " -m Stages.resolve_regroup"
    run_command(cmd)
end

function win.On.UpscaleBtn.Clicked(ev)
    if REPO_ROOT == "" then
        print("[Eternal2x] Missing repo_root in Eternal2x.conf.")
        return
    end
    local v = sensitivity_value()
    local cmd = "cd " .. shell_quote(REPO_ROOT)
        .. " && " .. shell_quote(PYTHON)
        .. " -m Stages.resolve_upscale_interpolate"
        .. " --sensitivity " .. string.format("%.4f", v)
    run_command(cmd)
end

win:Show()
disp:RunLoop()
