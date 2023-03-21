$(document).ready(function () {
    M.AutoInit();
});

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

function clear_date(id) {
    $("#" + id).val([]);
    M.Datepicker.getInstance($("#" + id)).setDate();
}

function datestr(datestr) {
    var splitDate = datestr.split("/");
    return new Date(splitDate[2], splitDate[1] - 1, splitDate[0]);
}

function toggle_hidden(show) {
    $(".hidden-entry").toggle()
    if (show) {
        $('#show-hidden').val("True")
    } else {
        $('#show-hidden').val("False")
    }
}