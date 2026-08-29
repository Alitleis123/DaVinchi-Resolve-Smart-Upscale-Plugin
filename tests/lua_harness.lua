-- Stubs enough of Fusion's UIManager / UIDispatcher and Resolve to load and
-- drive Installer/Eternal2x.lua outside of DaVinci Resolve.
--
-- Everything the script does to the outside world -- os.execute calls, print
-- output, config writes -- is captured for inspection.

local H = {}

H.commands = {}   -- every shell command the script ran, in order
H.prints = {}     -- every print() line
H.widgets = nil     -- widget table, keyed by ID
H.window = nil
H.exit_code = 0   -- what os.execute reports back

-- Widgets -----------------------------------------------------------------

local function new_widget(spec)
    local w = {}
    for k, v in pairs(spec) do
        if type(k) ~= "number" then w[k] = v end
    end
    w.__children = {}
    for _, child in ipairs(spec) do
        table.insert(w.__children, child)
    end
    return w
end

local function collect(widget, out)
    if widget.ID then out[widget.ID] = widget end
    for _, child in ipairs(widget.__children or {}) do
        collect(child, out)
    end
end

-- UIManager: ui:VGroup{...}, ui:Label{...} etc. all just build descriptors.
local ui = setmetatable({}, {
    __index = function(_, kind)
        return function(_self, spec)
            local w = new_widget(spec or {})
            w.__kind = kind
            return w
        end
    end,
})

-- Dispatcher --------------------------------------------------------------

local function auto_table()
    return setmetatable({}, {
        __index = function(t, k)
            local sub = {}
            rawset(t, k, sub)
            return sub
        end,
    })
end

local dispatcher = {}
dispatcher.__index = dispatcher

function dispatcher:AddWindow(attrs, layout)
    local win = {
        __attrs = attrs,
        __layout = layout,
        __shown = false,
        On = auto_table(),
    }
    local items = {}
    collect(layout, items)
    function win:GetItems() return items end
    function win:Show() self.__shown = true end
    function win:Hide() self.__shown = false end
    H.widgets = items
    H.window = win
    return win
end

function dispatcher:RunLoop() end
function dispatcher:ExitLoop() end

local bmd = {}
function bmd.UIDispatcher(_ui)
    return setmetatable({}, dispatcher)
end

-- Resolve stub ------------------------------------------------------------
-- Mirrors the shape Eternal2x.lua walks: project -> timeline -> item -> mpi.

function H.make_resolve(clip_file_path)
    local mpi = {
        GetClipProperty = function(_self)
            return { ["File Path"] = clip_file_path }
        end,
    }
    local item = { GetMediaPoolItem = function(_self) return mpi end }
    local timeline = {
        GetCurrentVideoItem = function(_self) return item end,
        GetSelectedItems = function(_self) return { item } end,
    }
    local project = { GetCurrentTimeline = function(_self) return timeline end }
    local pm = { GetCurrentProject = function(_self) return project end }
    return { GetProjectManager = function(_self) return pm end }
end

-- Loading -----------------------------------------------------------------

function H.load(script_path, clip_file_path)
    H.commands = {}
    H.prints = {}

    _G.fu = { UIManager = ui }
    _G.bmd = bmd

    package.preload["DaVinciResolveScript"] = function()
        return { scriptapp = function(name)
            if name == "Resolve" then return H.make_resolve(clip_file_path) end
            return nil
        end }
    end

    local real_execute = os.execute
    local real_print = print

    os.execute = function(cmd)
        table.insert(H.commands, cmd)
        return H.exit_code == 0, "exit", H.exit_code
    end
    print = function(...)
        local parts = {}
        for i = 1, select("#", ...) do
            parts[#parts + 1] = tostring((select(i, ...)))
        end
        table.insert(H.prints, table.concat(parts, "\t"))
    end

    local ok, err = pcall(dofile, script_path)

    os.execute = real_execute
    print = real_print

    if not ok then error(err) end
    return H.window
end

-- Inspection helpers used from the Python tests ---------------------------

function H.click(id)
    local handler = H.window.On[id] and H.window.On[id].Clicked
    if not handler then error("no Clicked handler for " .. tostring(id)) end
    local real_execute = os.execute
    local real_print = print
    os.execute = function(cmd)
        table.insert(H.commands, cmd)
        return H.exit_code == 0, "exit", H.exit_code
    end
    print = function(...) end
    local ok, err = pcall(handler, {})
    os.execute = real_execute
    print = real_print
    if not ok then error(err) end
end

function H.set_slider(id, value)
    H.widgets[id].Value = value
    local handler = H.window.On[id] and H.window.On[id].ValueChanged
    if handler then handler({}) end
end

function H.command_count() return #H.commands end
function H.command_at(i) return H.commands[i] end
function H.last_command() return H.commands[#H.commands] end
function H.status() return H.widgets.Status and H.widgets.Status.Text or nil end
function H.text_of(id) return H.widgets[id] and H.widgets[id].Text or nil end
function H.widget_ids()
    local ids = {}
    for id, _ in pairs(H.widgets) do table.insert(ids, id) end
    table.sort(ids)
    return table.concat(ids, ",")
end
function H.handler_ids()
    local ids = {}
    for id, events in pairs(H.window.On) do
        for ev, _ in pairs(events) do
            table.insert(ids, id .. "." .. ev)
        end
    end
    table.sort(ids)
    return table.concat(ids, ",")
end

return H
