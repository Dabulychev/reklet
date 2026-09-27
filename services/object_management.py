from copy import deepcopy


def calculate_object_management_change(
    old_state,
    correction,
    manufactured_action,
    shipped_action,
    delivered_action,
    installed_action,
):
    """Calculate one object-item management change without touching the database.

    Returns a dictionary with:
    state, commands, newly_produced_from_new, and error.
    """
    state = deepcopy(old_state)
    commands = []
    newly_produced_from_new = 0

    if any(
        value < 0
        for value in (
            manufactured_action,
            shipped_action,
            delivered_action,
            installed_action,
        )
    ):
        return {
            "state": state,
            "commands": commands,
            "newly_produced_from_new": newly_produced_from_new,
            "error": "действия производства/склада/транспорта/монтажа не могут быть отрицательными.",
        }

    # Order correction changes only the unprocessed part.
    # A reduction cannot invalidate quantities already in the chain.
    if correction < 0:
        decrease = -correction
        if decrease > state["new"]:
            return {
                "state": state,
                "commands": commands,
                "newly_produced_from_new": newly_produced_from_new,
                "error": (
                    f"нельзя уменьшить заказ на {decrease}; "
                    f"необработанный остаток заказа только {state['new']}."
                ),
            }
        state["order"] -= decrease
        state["new"] -= decrease
    elif correction > 0:
        state["order"] += correction
        state["new"] += correction

    # Every green field is a one-time movement command.
    # Missing upstream stock is generated automatically from the same order.
    for action_name, action_qty, action_kind in (
        ("изготовление", manufactured_action, "production"),
        ("отгрузка", shipped_action, "ship"),
        ("доставка", delivered_action, "arrive"),
        ("установка", installed_action, "install"),
    ):
        if not action_qty:
            continue

        try:
            if action_kind == "production":
                from_production = min(action_qty, state["production"])
                from_new = action_qty - from_production

                if from_new > state["new"]:
                    available = state["production"] + state["new"]
                    raise ValueError(
                        f"для изготовления {action_qty} шт. доступно только {available} шт."
                    )

                if from_production:
                    state["production"] -= from_production

                if from_new:
                    state["new"] -= from_new
                    newly_produced_from_new += from_new

                state["ready"] += action_qty
                commands.append(("production", action_qty))

            elif action_kind == "ship":
                shortage = max(action_qty - state["ready"], 0)
                if shortage:
                    # Ensure warehouse quantity by completing production.
                    from_production = min(shortage, state["production"])
                    from_new = shortage - from_production

                    if from_new > state["new"]:
                        available = state["production"] + state["new"]
                        raise ValueError(
                            f"для изготовления {shortage} шт. доступно только {available} шт."
                        )

                    if from_production:
                        state["production"] -= from_production

                    if from_new:
                        state["new"] -= from_new
                        newly_produced_from_new += from_new

                    state["ready"] += shortage
                    commands.append(("production", shortage))

                state["ready"] -= action_qty
                state["shipped"] += action_qty
                commands.append(("ship", action_qty))

            elif action_kind == "arrive":
                shortage = max(action_qty - state["shipped"], 0)
                if shortage:
                    # Ensure transport quantity by first ensuring warehouse quantity.
                    ready_shortage = max(shortage - state["ready"], 0)
                    if ready_shortage:
                        from_production = min(ready_shortage, state["production"])
                        from_new = ready_shortage - from_production

                        if from_new > state["new"]:
                            available = state["production"] + state["new"]
                            raise ValueError(
                                f"для изготовления {ready_shortage} шт. доступно только {available} шт."
                            )

                        if from_production:
                            state["production"] -= from_production

                        if from_new:
                            state["new"] -= from_new
                            newly_produced_from_new += from_new

                        state["ready"] += ready_shortage
                        commands.append(("production", ready_shortage))

                    state["ready"] -= shortage
                    state["shipped"] += shortage
                    commands.append(("ship", shortage))

                state["shipped"] -= action_qty
                state["arrived"] += action_qty
                commands.append(("arrive", action_qty))

            elif action_kind == "install":
                shortage = max(action_qty - state["arrived"], 0)
                if shortage:
                    # Ensure object quantity by ensuring transport first.
                    shipped_shortage = max(shortage - state["shipped"], 0)
                    if shipped_shortage:
                        ready_shortage = max(shipped_shortage - state["ready"], 0)
                        if ready_shortage:
                            from_production = min(
                                ready_shortage,
                                state["production"],
                            )
                            from_new = ready_shortage - from_production

                            if from_new > state["new"]:
                                available = state["production"] + state["new"]
                                raise ValueError(
                                    f"для изготовления {ready_shortage} шт. доступно только {available} шт."
                                )

                            if from_production:
                                state["production"] -= from_production

                            if from_new:
                                state["new"] -= from_new
                                newly_produced_from_new += from_new

                            state["ready"] += ready_shortage
                            commands.append(("production", ready_shortage))

                        state["ready"] -= shipped_shortage
                        state["shipped"] += shipped_shortage
                        commands.append(("ship", shipped_shortage))

                    state["shipped"] -= shortage
                    state["arrived"] += shortage
                    commands.append(("arrive", shortage))

                state["arrived"] -= action_qty
                state["installed"] += action_qty
                commands.append(("install", action_qty))

        except ValueError as exc:
            return {
                "state": state,
                "commands": commands,
                "newly_produced_from_new": newly_produced_from_new,
                "error": f"{action_name} {action_qty} шт. — {exc}",
            }

    allocated = (
        state["production"]
        + state["ready"]
        + state["shipped"]
        + state["arrived"]
        + state["installing"]
        + state["installed"]
    )

    if allocated > state["order"]:
        return {
            "state": state,
            "commands": commands,
            "newly_produced_from_new": newly_produced_from_new,
            "error": (
                f"итоговое количество {allocated} шт. "
                f"превышает заказ {state['order']} шт."
            ),
        }

    
    state["new"] = state["order"] - allocated

    return {
        "state": state,
        "commands": commands,
        "newly_produced_from_new": newly_produced_from_new,
        "error": None,
    }
