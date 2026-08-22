/* ==========================================================
   VIGILOX TABS
   PHASE 8.10
   ==========================================================

   An accessible tab controller for the document workspace.

   WHY TABS HERE
   ----------------------------------------------------------
   The workspace has six detail views: extracted data,
   validation, findings, final record, history and technical
   data. Stacked as sections they push the source document off
   a laptop screen, and a reviewer needs one of them at a time
   while looking at the image.

   Overview and Human Review are deliberately NOT tabs. Those
   are the status and the action, and they stay visible.


   THE PATTERN
   ----------------------------------------------------------
   Follows the ARIA tabs pattern with manual activation:

       one tab in the tab order at a time (roving tabindex)
       Left / Right move between tabs
       Home / End jump to the ends
       aria-selected marks the active tab
       each panel is labelled by its own tab

   Manual rather than automatic activation, because two of
   these panels are long and arrow-keying through them with
   automatic activation would move focus into content the user
   was only passing over.
   ========================================================== */

(function (global) {
    "use strict";


    /**
     * Wire a tablist.
     *
     * `tablist` is the container carrying role="tablist". Tabs
     * are discovered from it, and each tab names its panel
     * through aria-controls, so the HTML stays the single
     * source of truth for the pairing.
     */
    function createTabs(tablist, options) {
        var config = options || {};

        if (!tablist) {
            return null;
        }

        var tabs = Array.prototype.slice.call(
            tablist.querySelectorAll('[role="tab"]')
        );

        if (!tabs.length) {
            return null;
        }

        function panelFor(tab) {
            var id = tab.getAttribute("aria-controls");
            return id ? global.document.getElementById(id) : null;
        }

        function select(target, moveFocus) {
            tabs.forEach(function (tab) {
                var isActive = tab === target;
                var panel = panelFor(tab);

                tab.setAttribute(
                    "aria-selected",
                    isActive ? "true" : "false"
                );

                /* Roving tabindex: only the active tab is in
                   the tab order, so Tab moves out of the
                   tablist rather than through six buttons. */
                if (isActive) {
                    tab.removeAttribute("tabindex");
                    tab.classList.add("is-active");
                } else {
                    tab.setAttribute("tabindex", "-1");
                    tab.classList.remove("is-active");
                }

                if (panel) {
                    panel.hidden = !isActive;
                }
            });

            if (moveFocus && target.focus) {
                target.focus();
            }

            if (typeof config.onSelect === "function") {
                config.onSelect(target.id, target);
            }
        }

        function indexOfActive() {
            var found = 0;
            tabs.forEach(function (tab, index) {
                if (tab.getAttribute("aria-selected") === "true") {
                    found = index;
                }
            });
            return found;
        }

        function move(delta) {
            var next =
                (indexOfActive() + delta + tabs.length) % tabs.length;
            select(tabs[next], true);
        }

        tabs.forEach(function (tab) {
            tab.addEventListener("click", function () {
                select(tab, false);
            });

            tab.addEventListener("keydown", function (event) {
                var key = event.key;

                if (key === "ArrowRight" || key === "ArrowDown") {
                    if (event.preventDefault) {
                        event.preventDefault();
                    }
                    move(1);
                    return;
                }

                if (key === "ArrowLeft" || key === "ArrowUp") {
                    if (event.preventDefault) {
                        event.preventDefault();
                    }
                    move(-1);
                    return;
                }

                if (key === "Home") {
                    if (event.preventDefault) {
                        event.preventDefault();
                    }
                    select(tabs[0], true);
                    return;
                }

                if (key === "End") {
                    if (event.preventDefault) {
                        event.preventDefault();
                    }
                    select(tabs[tabs.length - 1], true);
                }
            });
        });

        /* Normalise the starting state from the markup rather
           than assuming the first tab, so a page can ship with
           a different default. */
        select(tabs[indexOfActive()], false);

        return {
            tabs: tabs,
            select: function (tabId) {
                var target = null;
                tabs.forEach(function (tab) {
                    if (tab.id === tabId) {
                        target = tab;
                    }
                });
                if (target) {
                    select(target, false);
                }
                return Boolean(target);
            },
            activeId: function () {
                return tabs[indexOfActive()].id;
            }
        };
    }


    global.VigiloxTabs = {
        createTabs: createTabs
    };

}(typeof window !== "undefined" ? window : globalThis));
