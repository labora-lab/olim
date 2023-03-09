function toggle_pannel(id) {
    $("#short_" + id).toggle();
    $("#text_" + id).toggle();
}

function toggle_day(id) {
    $(".toggle_inline_" + id).each(toggle_inline);
    $(".toggle_" + id).toggle();
}

function toggle_inline() {
    if ($(this).is(':visible'))
        $(this).css('display', 'none');
    else
        $(this).css('display', 'inline-block');
}

function toggle_hidden() {
    $(".hidden-entry").toggle()
}