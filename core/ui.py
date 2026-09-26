import streamlit as st


def data_editor_ru(df, **kwargs):
    return st.data_editor(df, **kwargs)


def _select_nav_item(state_key, option):
    # Store the active section in both session state and the URL.
    # The URL copy prevents a form/data_editor submit or a Streamlit
    # reconnect from falling back to the first menu item.
    st.session_state[state_key] = option
    st.query_params[f"nav_{state_key}"] = option


def render_button_nav(options, state_key, key_prefix, columns_per_row=None):
    """Render rectangular navigation with persistent section selection."""
    param_key = f"nav_{state_key}"
    url_value = st.query_params.get(param_key)

    if url_value in options:
        st.session_state[state_key] = url_value
    elif (
        state_key not in st.session_state
        or st.session_state[state_key] not in options
    ):
        st.session_state[state_key] = options[0]
        st.query_params[param_key] = options[0]

    if columns_per_row is None:
        columns_per_row = len(options)

    for start in range(0, len(options), columns_per_row):
        row = options[start:start + columns_per_row]
        cols = st.columns(len(row), gap="small")

        for col, option in zip(cols, row):
            with col:
                st.button(
                    option,
                    key=f"{key_prefix}_{start}_{option}",
                    use_container_width=True,
                    on_click=_select_nav_item,
                    args=(state_key, option),
                )

    return st.session_state[state_key]
